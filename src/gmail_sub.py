import calendar
import os
import threading
import time
from datetime import datetime, timezone

import apiclient
import httplib2
import oauth2client

credential_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "../token.json")


def credentials():
    store = oauth2client.file.Storage(credential_path)
    return store.get()


def service():
    http = credentials().authorize(httplib2.Http())
    return apiclient.discovery.build("gmail", "v1", http=http, cache_discovery=False)


def get_messages_list(user_id, from_address, after):
    if from_address is None:
        query = f"after:{after}"
    else:
        query = f"from:{from_address} after:{after}"
    return service().users().messages() \
        .list(userId=user_id, q=query).execute()


def get_message_detail(id, user_id):
    return service().users().messages().get(id=id, userId=user_id).execute()


class GmailSub():
    interval = 1
    is_running = True
    last_time = None
    from_address = None
    message_handler = None
    error_handler = None

    def __init__(self, user_id):
        self.user_id = user_id
        self.thread = threading.Thread(target=self.__start)
        self.thread.daemon = True
        self.thread.start()

    def set_interval(self, interval):
        self.interval = interval

    def set_from_address(self, address):
        self.from_address = address

    def on_message(self, callback):
        self.message_handler = callback

    def on_error(self, callback):
        self.error_handler = callback

    def stop(self):
        self.is_running = False

    def __start(self):
        while self.is_running:
            try:
                ms = self.__get_messages()
                if self.message_handler is not None:
                    self.message_handler(ms)
            except Exception as ex:
                if self.error_handler is not None:
                    self.error_handler(ex)
            time.sleep(self.interval)

    def __get_messages(self):
        if self.last_time is None:
            after = calendar.timegm(datetime.now(timezone.utc).timetuple())
        else:
            after = self.last_time + 1

        now = calendar.timegm(datetime.now(timezone.utc).timetuple())
        resp = get_messages_list(self.user_id,
                                 from_address=self.from_address,
                                 after=after)
        messages = []

        self.last_time = now

        if 'messages' not in resp:
            return messages
        for m in resp['messages']:
            detail = get_message_detail(m['id'], self.user_id)
            messages.append(detail)

        return messages
