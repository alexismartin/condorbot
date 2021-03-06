def init(config_filename):
    global BOT_COMMAND_PREFIX
    global BOT_VERSION

    global SEASON_YEAR

    #admin
    global ADMIN_ROLE_NAMES                     #list of names of roles to give admin access

    #channels
    global MAIN_CHANNEL_NAME
    global ADMIN_CHANNEL_NAME
    global SCHEDULE_CHANNEL_NAME
    global NOTIFICATIONS_CHANNEL_NAME

    #prerace
    global RACE_NUMBER_OF_RACES
    global RACE_ALERT_AT_MINUTES
    global RACE_NOTIFY_IF_TIMES_WITHIN_SEC

    #race
    global COUNTDOWN_LENGTH                        #number of seconds between the final .ready and race start
    global INCREMENTAL_COUNTDOWN_START             #number of seconds at which to start counting down each second in chat
    global FINALIZE_TIME_SEC                       #seconds after race end to finalize+record race

    #database
    global DB_FILENAME

    #gsheets
    global GSHEET_CREDENTIALS_FILENAME
    global GSHEET_DOC_NAME
    global GSHEET_TIMEZONE
    
    defaults = {
        'bot_command_prefix':'.',
        'bot_version':'0.1.0',
        'year':'2016',
        'channel_main':'season4',
        'channel_admin':'adminchat',
        'channel_schedule':'schedule',
        'channel_notifications':'bot_notifications',
        'race_number_of_races':'3',
        'race_alert_at_minutes':'30',
        'race_countdown_time_seconds':'10',
        'race_begin_counting_down_at':'5',
        'race_end_after_first_done_seconds':'15',
        'race_notify_if_times_within_seconds':'5',
        'db_filename':'data/ndwc.db',
        'gsheet_credentials_filename':'data/gsheet_credentials.json',
        'gsheet_doc_name':'CoNDOR Season 4',
        'gsheet_timezone':'US/Eastern',
        }

    admin_roles = []
            
    file = open(config_filename, 'r')
    if file:
        for line in file:
            args = line.split('=')
            if len(args) == 2:
                if args[0] in defaults:
                    defaults[args[0]] = args[1].rstrip('\n')
                elif args[0] == 'admin_roles':
                    arglist = args[1].rstrip('\n').split(',')
                    for arg in arglist:
                        admin_roles.append(arg)
                else:
                    print("Error in {0}: variable {1} isn't recognized.".format(config_filename, args[0]))

    BOT_COMMAND_PREFIX = defaults['bot_command_prefix']
    BOT_VERSION = defaults['bot_version']

    SEASON_YEAR = int(defaults['year'])
    
    MAIN_CHANNEL_NAME = defaults['channel_main']
    ADMIN_CHANNEL_NAME = defaults['channel_admin']
    SCHEDULE_CHANNEL_NAME = defaults['channel_schedule']
    NOTIFICATIONS_CHANNEL_NAME = defaults['channel_notifications']

    ADMIN_ROLE_NAMES = admin_roles

    RACE_NUMBER_OF_RACES = int(defaults['race_number_of_races'])
    RACE_ALERT_AT_MINUTES = int(defaults['race_alert_at_minutes'])
    RACE_NOTIFY_IF_TIMES_WITHIN_SEC = int(defaults['race_notify_if_times_within_seconds'])
    COUNTDOWN_LENGTH = int(defaults['race_countdown_time_seconds'])
    INCREMENTAL_COUNTDOWN_START = int(defaults['race_begin_counting_down_at'])
    FINALIZE_TIME_SEC = int(defaults['race_end_after_first_done_seconds'])

    DB_FILENAME = defaults['db_filename']
    GSHEET_CREDENTIALS_FILENAME = defaults['gsheet_credentials_filename']
    GSHEET_DOC_NAME = defaults['gsheet_doc_name']
    GSHEET_TIMEZONE = defaults['gsheet_timezone']
