#!/usr/bin/env python

import select
#~ import signal
import socket
import sys
import os
import logging
import json
import random
import threading
import trueskill
import subprocess

from math import ceil, sqrt
from time import time,sleep
import json

from time import time,asctime
import datetime

from ants import Ants
from engine import run_game

import game_db


# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# create formatter
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
# add formatter to ch
ch.setFormatter(formatter)

# create logger
log = logging.getLogger('tcp')
log.setLevel(logging.INFO)
# add ch to logger
log.addHandler(ch)

BUFSIZ = 4096

MAP_PLAYERS_INDEX = 0
MAP_COLS_INDEX = 1
MAP_ROWS_INDEX = 2
MAP_GAMES_INDEX = 3

## ugly global
class Bookkeeper:
    players=set()
    games=set()

book = Bookkeeper()

#botsToKill = []

def load_map_info():
    maps={}
    for root,dirs,filenames in os.walk("maps"):
        for filename in filenames:
            file = os.path.join(root, filename)
            mf = open(file,"r")
            for line in mf:
                if line.startswith('players'):    p = int(line.split()[1])
                if line.startswith('rows'):        r = int(line.split()[1])
                if line.startswith('cols'):        c = int(line.split()[1])
            mf.close()
            maps[file] = [p,r,c,0]
    return maps

#
## sandbox impl
#
class TcpBox(threading.Thread):
    def __init__(self, sock):
        threading.Thread.__init__(self)
        self.sock = sock
        self.inp_lines = []

        #db stuff
        self.name =""
        self.game_id=0

        self.start()

    def __del__(self):
        try:
            book.players.remove( self.name )
        except: pass
        self._close()

    def run( self ):
        while self.sock:
            line=""
            while(self.sock):
                try:
                    c = self.sock.recv(1)
                except Exception, e:
                    self._close()
                    break
                if ( not c ):
                    break
                elif ( c=='\r' ):
                    continue
                elif ( c=='\n' ):
                    break
                else:
                    line += c
            if line:
                self.inp_lines.append(line)

    def _close(self):
        try:
            self.sock.close()
        except: pass
        self.sock = None

    def kill(self):
        try:
            self.write("end\nyou timed out.\n\n")
        except: pass

        self._close()


    def write(self, str):
        try:
            self.sock.sendall(str)
        except Exception, e:
            pass

    def write_line(self, line):
        return self.write(line + "\n")

    def read_line(self, timeout=0):
        if (len(self.inp_lines) == 0) or (not self.sock):
            return None
        line = self.inp_lines[0]
        self.inp_lines = self.inp_lines[1:]
        return line

    ## dummies
    def release(self):
        self._close()

    def pause(self):
        pass

    def resume(self):
        pass

    def read_error(self, timeout=0):
        return None


class TcpGame(threading.Thread):
    def __init__( self, id, opts, map_name, nplayers ):
        threading.Thread.__init__(self)
        self.id = id
        self.opts = opts
        self.players = []
        self.bot_status = []
        self.map_name = map_name
        self.nplayers = nplayers
        self.bots=[]
        self.ants = Ants(opts)

    def __del__(self):
        try:
            book.games.remove(self.id)
        except: pass
        for b in self.bots:
            b.kill()


    def run(self):
        starttime = time()
        log.info( "run game %d %s %s" % (self.id,self.map_name,self.players) )
        for i,p in enumerate(self.bots):
            p.write( "INFO: game " + str(self.id) + " " + str(self.map_name) + " : " + str(self.players) + "\n" )

        game_result = run_game(self.ants, self.bots, self.opts)

        try:
            states = game_result["status"]
        except:
            log.error("broken game %d: %s" % (self.id,game_result) )
            return
        if self.ants.turn < 1:
            log.error("broken game %d (0 turns)" % (self.id) )
            return
        scores = game_result["score"]
        ranks  = game_result["rank"]

        # count draws
        draws = 0
        hist = [0]*len(ranks)
        for r in ranks:
            hist[r] += 1
        for h in hist:
            if h>0:  draws += (h-1)

        # save replay, add playernames to it
        game_result['game_id'] = self.id
        game_result['playernames'] = []
        for i,p in enumerate(self.players):
            game_result['playernames'].append(p)

        # save to db
        db = game_db.GameDB()
        data = json.dumps(game_result)

        # TODO change this to fit the tournament id
        db.add_replay( 1, self.id, data )

        plr = {}
        for i,p in enumerate(self.players):
            plr[p] = (scores[i], states[i])
            # TOOD change this 1 to fit the tournament id
            db.update("insert into Tourn_GameIndex values(?, ?, ?, ?)",(None, 1, p, self.id))
        db.add_game( self.id, 1, self.map_name, self.ants.turn, draws,json.dumps(plr) )

        # update trueskill
        #~ if sum(ranks) >= len(ranks)-1:
        if self.opts['trueskill'] == 'jskills':
            self.calk_ranks_js( self.players, ranks, db )
        else : # default
            self.calc_ranks_py( self.players, ranks, db )
        #~ else:
            #~ log.error( "game "+str(self.id)+" : ranking unsuitable for trueskill " + str(ranks) )

        ## this should go out
        # update rankings
        for i, p in enumerate(db.retrieve("select bot_id from Tourn_Enries where tourn_id=1 order by skill desc",())):
            db.update_player_rank( 1, p[0], i+1 )
        db.con.commit()

        # dbg display
        ds = time() - starttime
        mins = int(ds / 60)
        secs = ds - mins*60
        log.info("saved game %d : %d turns %dm %2.2fs" % (self.id,self.ants.turn,mins,secs) )
        log.info("players: %s" % self.players)
        log.info("ranks  : %s   %s draws" % (ranks, draws) )
        log.info("scores : %s" % scores)
        log.info("status : %s" % states)


    def calc_ranks_py( self, players, ranks, db ):
        class TrueSkillPlayer(object):
            def __init__(self, name, skill, rank):
                self.name = name
                self.old_skill = skill
                self.skill = skill
                self.rank = rank

        ts_players = []
        for i, p in enumerate(players):
            pdata = db.get_player((1, p))
            ts_players.append( TrueSkillPlayer(i, (pdata[0][6],pdata[0][7]), ranks[i] ) )

        try:
            trueskill.AdjustPlayers(ts_players)
        except Exception, e:
            log.error(e)
            return

        for i, p in enumerate(players):
            mu    = ts_players[i].skill[0]
            sigma = ts_players[i].skill[1]
            skill = mu - sigma * 3
            db.update_player_skill(1, p, skill, mu,sigma );


    def calk_ranks_js( self, players, ranks, db ):
        ## java needs ';' as separator for win23, ':' for nix&mac
        sep = ':'
        if os.name == 'nt':
            sep=';'
        try:
            classpath = "jskills/JSkills_0.9.0.jar"+sep+"jskills"
            tsupdater = subprocess.Popen(["java", "-cp", classpath, "TSUpdate"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)

            lines = []
            for i,p in enumerate(players):
                pdata = db.get_player( (1, p) )
                lines.append("P %s %d %f %f\n" % (p, ranks[i], pdata[0][6], pdata[0][7]))

            for i,p in enumerate(players):
                tsupdater.stdin.write(lines[i])

            tsupdater.stdin.write("C\n")
            tsupdater.stdin.flush()
            tsupdater.wait()
        except Exception,e:
            log.error( str( e.split('\n')[0]) )
            return
        try:
            result =  tsupdater.stderr.readline().split()
            print result
            if result.find("Maximum iterations")>0:
                log.error( "jskills:  Maximum iterations reached")
                return
        except Exception,e:
            log.error( str(e) )

        for i,p in enumerate(players):
            # this might seem like a fragile way to handle the output of TSUpdate
            # but it is meant as a double check that we are getting good and
            # complete data back
            result =  tsupdater.stdout.readline().split()
            if len(result)<3:
                log.error("invalid jskill result " + str(result))
                return

            if str(p) != result[0]:
                log.error("Unexpected player name in TSUpdate result. %s != %s" % (player, result[0]))
                break
            ## hmm, java returns floats formatted like: 1,03 here, due to my locale(german) ?
            mu    = float(result[1].replace(",","."))
            sigma = float(result[2].replace(",","."))
            skill = mu -sigma * 3
            db.update_player_skill( 1, p, skill, mu, sigma )



class TCPGameServer(object):
    def __init__(self, opts, ip, port, maps):
        self.opts = opts
        self.maps = maps

        # tcp binding options
        self.ip = ip
        self.port = port
        self.backlog = 5

        self.bind()

    def addplayer(self, game, name, language, sock):
        print("addplayer called")
        p = self.db.get_player((1, name))
        if len(p)==1:
            pw = p[0][2]
            if pw != password:
                log.warning("invalid password for %s : %s : %s" % (name, pw, password) )
                sock.sendall("INFO: invalid password for %s : %s\n"% (name, password) )
                sock.sendall("killbot")
                ##sock.sendall("end\ngo\n")
                sock.close()
                return -1
        else:
            print("addplayer else case")
            self.db.add_bot(name, u_id, name, language)

        box = TcpBox(sock)
        box.name=name
        box.game_id = game.id
        game.bots.append( box )
        game.players.append(name)
        book.players.add(name)
        return len(game.bots)


    def bind(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.ip,self.port))
        log.info('Listening to port %d ...' % self.port)
        self.server.listen(self.backlog)


    def shutdown(self):
        log.info('Shutting down server...')
        self.server.close()
        self.server=None

    def select_map(self):
        ## try to find a map that does not need more players than available
        max_players = len(book.players)/2
        if max_players < 2:
            max_players = 2
        map_path = random.choice( self.maps.keys() )

        while( self.maps[map_path][MAP_PLAYERS_INDEX] > max_players ):
            map_path = random.choice( self.maps.keys() )
        self.maps[map_path][MAP_GAMES_INDEX] += 1

        data = ""
        f = open(map_path, 'r')
        for line in f:
            data += line
            if line.startswith('players'):
                nplayers = line.split()[1]
        f.close()
        return map_path, data, int(nplayers)


    def create_game(self):
        # get a map and create antsgame
        self.latest += 1
        map_name, map_data, nplayers = self.select_map()
        opts = self.opts
        opts['map'] = map_data

        log.info( "game %d %s needs %d players" %(self.latest,map_name,nplayers) )
        g = TcpGame( self.latest, opts, map_name, nplayers)
        book.games.add(g.id)
        return g


    def reject_client(self,client, message,dolog=True):
        try:
            if dolog:
                log.info(message)
            client.sendall("INFO: " + message + "\nend\ngo\n")
            client.close()
            client = None
        except:
            pass

    #def kill_bot(self, botname = ""):
    #    print("should be killing stuff")
    #    for b in self.bots:
    #        b.kill()

    #Bots are removed by removing their entries from the database
    #This checks if the connecting bot is in the database. If not it gets killed
    #def check_bot_kill()

    def kill_client(self, client, message, dolog=True, name = ""):
        try:
            if dolog:
                log.info(message)
            client.sendall("killbot" + message)
            client.close()
            client = None
            self.db.delete_kill_name(name)
        except:
            pass

    def serve(self):
        # have to create the game before collecting respective num of players:
        self.db = game_db.GameDB()
        self.kill_list = self.db.get_kill_client()
        games = self.db.retrieve("select id from Tourn_Games where tourn_id=1 order by id desc limit 1;",())
        if len(games) > 0:
            self.latest = int(games[0][0])
        else:
            self.latest = 0

        next_game = self.create_game()
        t = 0
        while self.server:
            try:
                inputready,outputready,exceptready = select.select([self.server], [], [], 0.1)
            except select.error, e:
                log.exception(e)
                break
            except socket.error, e:
                log.exception(e)
                break
            except KeyboardInterrupt, e:
                return

            try:
                for s in inputready:
                    if s == self.server:
                        # find the client connected to server
                        client, address = self.server.accept()
                        data = client.recv(4096).strip()
                        data = data.split(" ")
                        name = data[1]
                        password = data[2]
                        name_ok = True
                        
                        #it kinda works, but for loop needs to be redone
                        i = -1
                        for entry in self.kill_list:
                            if (entry[i] == name):
                                self.kill_client(client, "deleted because on kill_list", True, name)
                                break


                        for bw in ["shit","porn","pr0n","pron","dick","tits","hitler","fuck","gay","cunt","asshole"]:
                            if name.find(bw) > -1:
                                #self.reject_client(client, "can you think of another name than '%s', please ?" % name )
                                self.kill_client(client, "can you think of another name than '%s', please ?" % name )
                                name_ok = False
                                break
                        if not name_ok:
                            continue
                        # if in 'single game per player(name)' mode, just reject the connection here..
                        if (name in book.players) and (str(self.opts['multi_games'])=="False"):
                            self.reject_client(client, "%s is already running a game." % name, False )
                            continue
                        # already in next_game ?
                        if name in next_game.players:
                            self.reject_client(client, '%s is already queued for game %d' % (name, next_game.id), False )
                            continue

                        # start game if enough players joined
                        avail = self.addplayer( next_game, name, password, client )
                        if avail==-1:
                            continue
                        log.info('user %s connected to game %d (%d/%d)' % (name,next_game.id,avail,next_game.nplayers))
                        if avail == next_game.nplayers:
                            next_game.start()
                            next_game = self.create_game()

                # remove bots from next_game that died between connect and the start of the game
                for i, b in enumerate(next_game.bots):
                    if (not b.sock) or (not b.is_alive):
                        log.info( "removed %s from next_game:%d" % (b.name, next_game.id) )
                        del( next_game.bots[i] )
                        del( next_game.players[i] )

                if t % 25 == 1:
                    log.info("%d games, %d players online." % (len(book.games),len(book.players)) )
                    self.kill_list = self.db.get_kill_client()
                    print(book.players)

                #if t % 250 == 1:
                #    for player in book.players:
                #        print(player.name)
                #        print("hello?")

                t += 1

                sleep(0.005)
            except:
                pass

        self.shutdown()




def main(ip = '', tcp_port = 2081):

    opts = {
        ## tcp opts:
        'turns':750,
        'loadtime': 5000,
        'turntime': 5000,
        'viewradius2': 77,
        'attackradius2': 5,
        'spawnradius2': 1,
        'attack': 'focus',
        'food': 'symmetric',
        'food_rate': (1,8), # total food
        'food_turn': (12,30), # per turn
        'food_start': (75,175), # per land area
        'food_visible': (2,4), # in starting loc
        'cutoff_percent': 0.66,
        'cutoff_turn': 150,
        'kill_points': 2,

        ## non-ants related tcp opts
        'trueskill': 'jskills',    # select trueskill implementation: 'py'(trueskill.py) or 'jskills'(java JSkills_0.9.0.jar)
        'multi_games': 'True',  # allow users to play multiple games at the same time
                                # if set to False, players will have to wait until their latest game ended
    }
    maps = load_map_info()
    if len(maps) == 0:
        print("Error: Found no maps! Please create a few in the maps/ folder.")
        return

    tcp = TCPGameServer( opts, ip, tcp_port, maps )
    tcp.serve()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 3:
        import os
        fpid = os.fork()
        if fpid!=0:
          # Running as daemon now. PID is fpid
          sys.exit(0)
    elif len(sys.argv) > 2:
        main(sys.argv[1], int(sys.argv[2]))
    elif len(sys.argv) > 1:
        main(int(sys.argv[1]))
    else:
        main()
