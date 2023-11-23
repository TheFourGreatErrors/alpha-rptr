# coding: UTF-8

import importlib, os, sys, shutil, textwrap

import json #pickle #jsonpickle #json

from src import logger, query_yes_no, symlink
from src.config import config as conf

class BotFactory():

    @staticmethod
    def create(args):
        """
        This Function creates the bot.
        :param args: stratergy's args.
        :return: Bot
        """
        try:
            strategy_module = importlib.import_module("src.strategies."+args.strategy)
            cls = getattr(strategy_module, args.strategy)
            bot = cls()
            bot.test_net  = args.demo
            bot.back_test = args.test
            bot.stub_test = args.stub
            bot.spot = args.spot
            bot.hyperopt  = args.hyperopt
            bot.account = args.account
            bot.exchange_arg = args.exchange
            bot.pair = args.pair
            bot.plot = args.plot

            if conf["args"].html_report:
                STRATEGY_FILENAME = os.path.join(os.getcwd(), f"src/strategies/{args.strategy}.py")

                with open(STRATEGY_FILENAME, 'r') as file:
                    original_content = file.read()

                updated_content = f"""
                #####################
                #
                # Command: {' '.join(sys.argv)}  
                #
                #####################
                """
                updated_content = textwrap.dedent(updated_content)

                updated_content = updated_content + original_content

                with open('html/data/strategy.py', 'w') as file:
                    file.write(updated_content)

                #shutil.copy(STRATEGY_FILENAME, 'html/data/strategy.py')
            
            if args.session != None:
                try:
                    bot.session_file_name = args.session
                    bot.session_file = open(args.session,"r+")
                except Exception as e:
                    logger.info("Session file not found - Creating!")
                    bot.session_file = open(args.session,"w")
                
                try:
                    # vars = pickle.load(bot.session_file)
                    vars = json.load(bot.session_file)
                    # vars = jsonpickle.decode(bot.session_file.read())

                    use_stored_session = query_yes_no("Session Found. Do you want to use it?", "no")
                    if use_stored_session:
                        bot.set_session(vars)
                except Exception as _:
                    logger.info("Session file is empty!")
            else:
                bot.session_file = None

            return bot
        except Exception as _:
            raise Exception(f"Not Found Strategy : {args.strategy}")