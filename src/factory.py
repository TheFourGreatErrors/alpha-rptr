# coding: UTF-8

import src.strategy as strategy


class BotFactory():

    @staticmethod
    def create(args):
        """
        This Function creates the bot.
        :param args: stratergy's args.
        :return: Bot
        """
        try:
            cls = getattr(strategy, args.strategy)
            bot = cls()
            bot.test_net  = args.demo
            bot.back_test = args.test
            bot.stub_test = args.stub
            bot.hyperopt  = args.hyperopt
            bot.account = args.account
            bot.exchange_arg = args.exchange
            bot.pair = args.pair
            return bot
        except Exception as _:
            raise Exception(f"Not Found Strategy : {args.strategy}")
