FROM heroku/heroku:16

RUN apt-get update && apt-get install -y \
    gcc \
    python3-pip \
    libsm6 \
    build-essential \
    cmake \
    pkg-config \
    libx11-dev \
    libatlas-base-dev \
    libgtk-3-dev \
    libboost-python-dev

RUN cd /tmp && \
    wget -O ta-lib.tar.gz http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar xvzf ta-lib.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr && \
    make && make install

ADD ./requirements.txt /tmp/requirements.txt

RUN pip3 install -r /tmp/requirements.txt

ADD ./ /opt/webapp/
WORKDIR /opt/webapp

CMD python3 main.py --test --account binanceaccount1 --exchange binanace --pair BTCUSDT --strategy Sample
