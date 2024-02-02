import time
import threading
from src import logger, notify


class Monitor:
    """
    A simple Monitor to check on periodic events like websocket updates.

    You can register a topic and callback with this singleton class and set the
    maximum interval between pings on that topic. And when a ping (method call) 
    is not received on that topic within the timeout period after the previous ping, 
    Monitor will trigger the callback once allowing for corrective actions and alerts.

    # Example usage:
    def callback_function(topic):
        print(f"Callback triggered for topic: {topic}")
        #do alerts, etc.

    # Get Monitor
    monitor = Monitor()

    # Register callbacks with topics and timeout periods
    monitor.register_callback("public_ws", callback_function, 120)
    monitor.register_callback("private_ws", callback_function, 120)

    # Simulate pinging topics (you would call this periodically in your application)
    monitor.ping_topic("public_ws")
    monitor.ping_topic("private_ws")

    """
    instance = None
    lock = threading.Lock()  # Class level lock to protect singleton creation.

    def __new__(cls):
        with Monitor.lock:
            if Monitor.instance is None:
                Monitor.instance = super(Monitor, cls).__new__(cls)
        return Monitor.instance

    def __init__(self):
        self.topic_callbacks = {}
        self.timeout_thread = threading.Thread(target=self._check_timeouts, daemon=True)
        self.timeout_thread.start()

    def _check_timeouts(self):
        while True:
            time.sleep(5)  # Adjust the sleep interval as needed
            with self.lock:
                current_time = time.time()
                for topic, data in list(self.topic_callbacks.items()):
                    elapsed_time = current_time - data['last_ping_time']
                    if elapsed_time >= data['timeout'] and not data["timedout"]:
                        # flag the topic to prevent multiple callbacks  
                        self.topic_callbacks[topic]["timedout"] = True 
                        # Trigger the callback if timeout has occurred
                        try:
                            data['callback'](topic)
                        except Exception as e:
                            logger.info(f"Monitor Exception: {e}")
                                       
    def register_callback(self, topic, callback, timeout_seconds):
        with self.lock:
            if topic not in self.topic_callbacks:
                self.topic_callbacks[topic] = {'callback': callback, 'timeout': timeout_seconds, 'last_ping_time': time.time(), 'timedout': False}

    def deregister_callback(self, topic):
        with self.lock:
            if topic in self.topic_callbacks:
                # remove the topic and callback
                del self.topic_callbacks[topic]

    def ping_topic(self, topic):
        with self.lock:
            if topic in self.topic_callbacks:
                self.topic_callbacks[topic]['last_ping_time'] = time.time()
                self.topic_callbacks[topic]['timedout'] = False

