#TODO intelligent handling of rate limiting
#TODO mod options for races (assist in cleanup)

## Handles bot actions for a single race room

import asyncio
import config
import datetime
import discord
import racetime
import sqlite3
import time
import pytz

from raceinfo import RaceInfo
from racer import Racer

RaceStatus = {'uninitialized':0, 'entry_open':1, 'counting_down':2, 'racing':3, 'paused':4, 'completed':5, 'finalized':6, 'cancelled':7}
StatusStrs = {'0':'Not initialized.', '1':'Waiting for racers to `.ready`.', '2':'Starting!', '3':'In progress!', '4':'Paused!', '5':'Complete.', '6':'Results Finalized.', '7':'Race Cancelled.'}
##    uninitialized   --  initialize() should be called on this object (not called in __init__ because coroutine)
##    entry_open      --  the race is open to new entrants
##    counting_down   --  the racebot is counting down to race start. if people .unready during this time, race reverts to the entry_open state
##    racing          --  the race has begun, and at least one player is still racing
##    race_completed  --  all players have either finished or forfeited. if players .undone during this time, race reverts to the racing state
##    race_finalized  --  all players have finished or forfeited, and the race results are marked as final and can be recorded. no further changes possible.

def status_str(race_status):
    return 'Race Status: {0}'.format(StatusStrs[str(race_status)]);

class Race(object):

    # NB: Call the coroutine initialize() to set up the room
    def __init__(self, race_room, race_info):
        self.room = race_room
        self.race_info = race_info                  #Information on the type of race (e.g. seeded, seed, character) -- see RaceInfo for details
        self.racers = dict()                        #a dictionary of racers indexed by user id
        self._status = RaceStatus['uninitialized']  #see RaceStatus

        self.no_entrants_time = None                #whenever there becomes zero entrance for the race, the time is stored here; used for cleanup code
        self._countdown = int(0)                    #the current countdown (TODO: is this the right implementation? unclear what is best)
        self._start_time = float(0)                 #system clock time for the beginning of the race (but is modified by pause())
        self._start_datetime = None                 #UTC time for the beginning of the race
        self._pause_time = float(0)                 #system clock time for last time we called pause()

        self._countdown_future = None               #The Future object for the race countdown
        self._finalize_future = None                #The Future object for the finalization countdown

    # Sets up the leaderboard, etc., for the race
    @asyncio.coroutine
    def initialize(self):
        if self._status != RaceStatus['uninitialized']:
            return

        self._status = RaceStatus['entry_open'] 
        self.no_entrants_time = time.clock()
##        yield from self.room.write('Enter the race with `.enter`, and type `.ready` when ready. Finish the race with `.done` or `.forfeit`. Use `.help` for a command list.')

    # Returns the race start datetime (UTC)
    @property
    def start_time(self):
        if self._start_datetime:
            return pytz.utc.localize(self._start_datetime)
        else:
            return None
                    
    # Returns a list of racers and their statuses.
    @property
    def leaderboard(self):
        racer_list = []
        max_name_len = 0
        max_time = 0
        for r_id in self.racers:
            racer = self.racers[r_id]
            max_name_len = max(max_name_len, len(racer.name))
            racer_list.append(racer)
            if racer.is_finished:
                max_time = max(racer.time, max_time)
        max_time += 1

        #Sort racers: (1) Finished racers, by time; (2) Forfeit racers; (3) Racers still racing
        racer_list.sort(key=lambda r: r.time if r.is_finished else (max_time if r.is_forfeit else max_time+1))

        text = self.race_info.seed_str() + '\n'
        text += status_str(self._status) + '\n'
        rank = int(0)
        for racer in racer_list:
            rank += 1
            rank_str = '{0: >4} '.format(str(rank) + '.' if racer.is_finished else ' ')
            text += (rank_str + racer.name + (' ' * (max_name_len - len(racer.name))) + ' --- ' + racer.status_str + '\n')
        return text

    # True if the given racer is entered in the race
    def has_racer(self, racer_usr):
        return racer_usr.id in self.racers

    # Returns the given racer if possible
    def get_racer(self, racer_usr):
        if self.has_racer(racer_usr):
            return self.racers[racer_usr.id]
        else:
            return None

    # Returns the current time elapsed as a string "[m]m:ss.hh"
    @property
    def current_time_str(self):
        if self._status == RaceStatus['paused']:
            return racetime.to_str( int(100*(self._pause_time - self._start_time)) )
        elif self._status == RaceStatus['racing']:
            return racetime.to_str( int(100*(time.clock() - self._start_time)) )
        else:
            return ''

    # Returns the number of racers not in the 'ready' state
    @property
    def num_not_ready(self):
        num = 0
        for r_name in self.racers:
            if not self.racers[r_name].is_ready:
                num += 1
        return num

    # Return the number of racers in the 'finished' state
    @property
    def num_finished(self):
        num = 0
        for r_name in self.racers:
            if self.racers[r_name].is_finished:
                num += 1
        return num        

    @property
    def entry_open(self):
        return self._status == RaceStatus['entry_open']

    #True if the race has started
    @property
    def is_before_race(self):
        return self._status < RaceStatus['racing']

    #True if the race is finalized or cancelled
    @property
    def complete(self):
        return self._status >= RaceStatus['completed']

    # Begin the race countdown and transition race state from 'entry_open' to 'counting_down'
    @asyncio.coroutine
    def begin_race_countdown(self):
        if self._status == RaceStatus['entry_open']:
            self._status = RaceStatus['counting_down']
            self._countdown_future = asyncio.ensure_future(self._race_countdown())
            asyncio.ensure_future(self.room.update_leaderboard())

    @asyncio.coroutine
    # Pause the race timer. 
    def pause(self):
        if self._status == RaceStatus['racing']:
            self._status = RaceStatus['paused']
            self._pause_time = time.clock()
            asyncio.ensure_future(self.room.update_leaderboard())
            return True
        return False
    
    @asyncio.coroutine
    # Unpause the race timer.
    def unpause(self):
        if self._status == RaceStatus['paused']:
            self._status = RaceStatus['racing']
            self._start_time += time.clock() - self._pause_time
            asyncio.ensure_future(self.room.update_leaderboard())
            return True
        return False
    
    # Begins the race. Called by the countdown.
    @asyncio.coroutine
    def _begin_race(self):
        for r_id in self.racers:
            if not self.racers[r_id].begin_race():
                print("{} isn't ready while calling race.begin_race -- unexpected error.".format(racer.name))

        self._start_time = time.clock()
        self._start_datetime = datetime.datetime.utcnow()
        yield from self.room.write('GO!')
        self._status = RaceStatus['racing']
        asyncio.ensure_future(self.room.update_leaderboard())

    # Checks to see if any racer has either finished or forfeited. If so, ends the race.
    # Return True if race was ended.
    @asyncio.coroutine
    def _check_for_race_end(self):
        for r_id in self.racers:
            if self.racers[r_id].is_done_racing:
                yield from self._end_race()
                return True

        return False

    # Ends the race, and begins a countdown until the results are 'finalized' (record results, and racers can no longer `.undone`, `.comment`, etc)
    @asyncio.coroutine
    def _end_race(self):
        if self._status == RaceStatus['racing']:
            self._status = RaceStatus['completed']
            self._finalize_future = asyncio.ensure_future(self._finalization_countdown())

    # Countdown coroutine to be wrapped in self._countdown_future.
    # Warning: Do not call this -- use begin_countdown instead.
    @asyncio.coroutine
    def _race_countdown(self):
        countdown_timer = config.COUNTDOWN_LENGTH
        yield from asyncio.sleep(1) #Pause before countdown
        
        yield from self.room.write('The race will begin in {0} seconds.'.format(countdown_timer))
        while countdown_timer > 0:
            if countdown_timer <= config.INCREMENTAL_COUNTDOWN_START:
                yield from self.room.write('{}'.format(countdown_timer))
            yield from asyncio.sleep(1) #sleep for a second
            countdown_timer -= 1

        #Begin the race. At this point, ignore cancel() requests
        try:
            yield from self._begin_race()
        except CancelledError:
            if self._status != RaceStatus['racing']:
                yield from self._begin_race()

    # Countdown coroutine to be wrapped in self._finalize_future.
    # Warning: Do not call this -- use end_race instead.
    @asyncio.coroutine
    def _finalization_countdown(self):
        asyncio.ensure_future(self.room.update_leaderboard())

        yield from asyncio.sleep(1) # Waiting for a short time feels good UI-wise
        yield from self.room.write('The race will end in {} seconds.'.format(config.FINALIZE_TIME_SEC))
        yield from asyncio.sleep(config.FINALIZE_TIME_SEC)       
        yield from self._finalize_race()
            
    # Finalizes the race
    @asyncio.coroutine
    def _finalize_race(self):
        self._status = RaceStatus['finalized'] if self.num_finished else RaceStatus['cancelled']
        yield from self.room.record_race()

    # Attempt to cancel the race countdown -- transition race state from 'counting_down' to 'entry_open'
    # Returns False only if there IS a countdown, AND we failed to cancel it
    @asyncio.coroutine
    def cancel_countdown(self, display_msgs=True):
        if self._status == RaceStatus['counting_down']:
            if self._countdown_future:
                if self._countdown_future.cancel():
                    self._countdown_future = None
                    self._status = RaceStatus['entry_open']
                    asyncio.ensure_future(self.room.update_leaderboard())
                    if display_msgs:
                        yield from self.room.write('Countdown cancelled.')
                    return True
                else:
                    return False
        return True

    # Attempt to cancel finalization and restart race -- transition race state from 'completed' to 'racing'
    # Returns False only if race IS completed, AND we failed to restart it
    @asyncio.coroutine
    def cancel_finalization(self, display_msgs=True):
        if self._status == RaceStatus['completed']:
            if self._finalize_future:
                if self._finalize_future.cancel():
                    self._finalize_future = None
                    self._status = RaceStatus['racing']
                    asyncio.ensure_future(self.room.update_leaderboard())
                    if display_msgs:
                        yield from self.room.write('Race end cancelled -- unfinished racers may continue!')
                    return True
                else:
                    return False
        return True

    # Enters the given discord Member in the race
    @asyncio.coroutine
    def enter_racer(self, racer_member):
        if self._status == RaceStatus['entry_open'] and not self.has_racer(racer_member):
            racer = Racer(racer_member)
            self.racers[racer_member.id] = racer
            asyncio.ensure_future(self.room.update_leaderboard())
            return True
        else:
            return False

    # Unenters the given discord Member in the race
    @asyncio.coroutine
    def unenter_racer(self, racer_member):
        if self.has_racer(racer_member):
            del self.racers[racer_member.id]
            asyncio.ensure_future(self.room.update_leaderboard())
            if not self.racers:
                self.no_entrants_time = time.clock()
            if (len(self.racers) < 2 and config.REQUIRE_AT_LEAST_TWO_FOR_RACE) or len(self.racers) < 1:
                yield from self.cancel_countdown() #TODO: implement correct behavior if this fails
            return True
        else:
            return False

    # Puts the given Racer in the 'ready' state
    @asyncio.coroutine
    def ready_racer(self, racer):
        if racer.ready():
            asyncio.ensure_future(self.room.update_leaderboard())
            return True
        else:
            return False

    # Attempt to put the given Racer in the 'unready' state if they were ready
    @asyncio.coroutine
    def unready_racer(self, racer):
        # See if we can cancel a countdown. If cancel_countdown() returns False,
        # then there is a countdown and we failed to cancel it, so racer cannot be made unready.
        success = yield from self.cancel_countdown()
        if success and racer.unready(): 
            asyncio.ensure_future(self.room.update_leaderboard())
            return True
        else:
            return False

    # Puts the given Racer in the 'finished' state and gets their time
    @asyncio.coroutine
    def finish_racer(self, racer):
        if self.is_before_race:
            return False
        
        finish_time = int(100*(time.clock() - self._start_time))
        if racer and racer.finish(finish_time):
            asyncio.ensure_future(self._check_for_race_end())
            asyncio.ensure_future(self.room.update_leaderboard())
            return True
        return False

    # Attempt to put the given Racer in the 'racing' state if they were finished
    @asyncio.coroutine
    def unfinish_racer(self, racer):
        if self._status == RaceStatus['finalized'] or not racer.is_finished:
            return False
        
        # See if we can cancel a (possible) finalization. If cancel_finalization() returns False,
        # then there is a finalization and we failed to cancel it, so racer cannot be made unready.
        success = yield from self.cancel_finalization()
        if success and racer and racer.unfinish():
            asyncio.ensure_future(self.room.update_leaderboard())
            return True
        return False

    # Puts the given Racer in the 'forfeit' state
    @asyncio.coroutine
    def forfeit_racer(self, racer):
        forfeit_time = int(100*(time.clock() - self._start_time))
        if racer and racer.forfeit(forfeit_time):
            asyncio.ensure_future(self._check_for_race_end())
            asyncio.ensure_future(self.room.update_leaderboard())
            return True
        return False

    # Attempt to put the given Racer in the 'racing' state if they had forfeit
    @asyncio.coroutine
    def unforfeit_racer(self, racer):
        if self._status == RaceStatus['finalized'] or not racer.is_forfeit:
            return False
        
        # See if we can cancel a (possible) finalization. If cancel_finalization() returns False,
        # then there is a finalization and we failed to cancel it, so racer cannot be made unready.
        success = yield from self.cancel_finalization()
        if success and racer and racer.unforfeit():
            asyncio.ensure_future(self.room.update_leaderboard())
            return True
        return False

    # List the racers in order of finish time
    @property
    def racer_list(self):
        r_list = []
        max_time = 0
        for r_id in self.racers:
            racer = self.racers[r_id]
            r_list.append(racer)
            if racer.is_finished:
                max_time = max(racer.time, max_time)
        max_time += 1

        r_list.sort(key=lambda r: r.time if r.is_finished else max_time)
        return r_list

    # Cancel the race.
    @asyncio.coroutine
    def cancel(self):
        asyncio.ensure_future(self.cancel_countdown())
        yield from self.cancel_finalization()
        self._status = RaceStatus['cancelled']

##    # Reset the race.
##    @asyncio.coroutine
##    def reset(self):
##        asyncio.ensure_future(self.cancel_countdown())
##        success = yield from self.cancel_finalization()
##        self._status = RaceStatus['entry_open']
##        self.racers = []
##        self.no_entrants_time = time.clock()
##        yield from self.room.write('The race has been reset.')
##        asyncio.ensure_future(self.room.update_leaderboard())        
            

