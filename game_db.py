#!/usr/bin/env python

import sqlite3
import datetime
import zlib
import os
#~ import json

class GameDB():
	
	def __init__( self, file="antsdb.sqlite3" ):
		db_is_new = not os.path.exists(file)
		self.con = sqlite3.connect(file)
		self.recreate()
		
	def __del__( self ):
		try:
			self.con.close()
		except: pass
		
	def recreate( self ):
		cur = self.con.cursor()
		try:

			#### Users ####
			cur.execute("create table \
				Users(\
					id INTEGER PRIMARY KEY AUTOINCREMENT,\
					name TEXT UNIQUE,\
					password TEXT,\
					email TEXT\
				)")

			#### Bots ####
			cur.execute("create table \
				Bots(\
					id INTEGER PRIMARY KEY AUTOINCREMENT,\
					owner_id INTEGER,\
					name TEXT UNIQUE,\
					language TEXT\
				)")

			#### Tournaments ####
			cur.execute("create table \
				Tournaments(\
					id INTEGER PRIMARY KEY AUTOINCREMENT,\
					creator_id INTEGER,\
					name TEXT UNIQUE,\
					password TEXT,\
					start_date DATE,\
					end_date DATE\
				)")

			#### Gameindex ####
			cur.execute("create table \
				Tourn_GameIndex(\
					id INTEGER PRIMARY KEY AUTOINCREMENT,\
					tourn_id INTEGER,\
					player TEXT,\
					gameid INTEGER\
				)")

			#### Games ####
			cur.execute("create table \
				Tourn_Games(\
					id INTEGER primary key AUTOINCREMENT,\
					tourn_id INTEGER,\
					players TEXT,\
					map TEXT,\
					datum DATE,\
					turns INTEGER DEFAULT 0,\
					draws INTEGER DEFAULT 0\
				)")

			#### Bots_tournament ####
			cur.execute("create table \
				Tourn_Entries(\
					id INTEGER PRIMARY KEY AUTOINCREMENT,\
					tourn_id INTEGER,\
					bot_id INTEGER,\
					lastseen DATE,\
					rank INTEGER DEFAULT 1000,\
					skill real DEFAULT 0.0,\
					mu real DEFAULT 50.0,\
					sigma real DEFAULT 13.3,\
					ngames INTEGER DEFAULT 0,\
					status bit DEFAULT 1\
				)")

			#### Replays ####
			cur.execute("create table \
				Tourn_Replays(\
					id INTEGER,\
					tourn_id INTEGER,\
					json BLOB\
				)")

			#### Kill_client ####
			cur.execute("create table \
				kill_client(\
					name TEXT UNIQUE\
				)")

			if db_is_new:
				cur.execute("insert into Users \
					(id, name, password, email) \
					values (None, admin, cs460Ant, rcliao01@gmail.com)")
				cur.execute("insert into Trounaments \
					(id, creator_id, name, password, start_date, end_date) \
					values (None, 1, 'Main Tournaments', \
						datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S'), \
						datetime.MAXYEAR.strftime('%d.%m.%Y %H:%M:%S'))\
					")

			self.con.commit()
		except:
			pass

	#### SQL INTERFACE ####
			
	def now( self ):
		return datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S") #asctime()

	def update_defered( self, sql, tup=() ):
		cur = self.con.cursor()		
		cur.execute(sql,tup)
		
	def update( self, sql, tup=() ):
		self.update_defered(sql,tup)
		self.con.commit()
		
	def retrieve( self, sql, tup=() ):
		cur = self.con.cursor()		
		cur.execute(sql,tup)
		return cur.fetchall()

	#### READ ####

	def get_replay( self, t_id, id ):
		rep = self.retrieve("select json from Tourn_Replays where tourn_id=? AND id=?", (t_id, id) )
		return zlib.decompress(rep[0][0])

	def num_games( self, t_id ):
		return int(self.retrieve( "select count(*) from Tourn_Games where tourn_id=?", (t_id, ) )[0][0])

	def get_games( self, t_id, offset, num ):
		return self.retrieve( "select * from Tourn_Games where tourn_id=? order by id desc limit ? offset ?", (t_id, num, offset) )

	def get_games_for_player( self, t_id, offset, num, player):
		arr = self.retrieve( "select gameid from Tourn_GameIndex where tourn_id=? AND player=? order by gameid desc limit ? offset ?",
			(t_id, player, num, offset) )
		g = []
		for a in arr:
			z = self.retrieve( "select * from Tourn_Games where tourn_id=? AND id=?", (t_id, a[0]))
			g.append( z[0] )
		return g
	
	def num_games_for_player( self, t_id, player ):
		return int(self.retrieve( "select count(*) from Tourn_GameIndex where tourn_id=? AND player=?",
			( t_id, player ) )[0][0] )

	def num_players( self, t_id ):
		return int(self.retrieve( "select count(*) from Tourn_Entries where tourn_id=?", (t_id, ) )[0][0])

	def get_bots( self, username ):
		return self.retrieve("select * from Bots AS b INNER JOIN Users u on u.id=b.owner_id where u.name=?", (username, ))

	def authenticate_user( self, name, password ):
		return self.retrieve("select id from Users where name=? AND password=?", (name, password))

	# Checks if a username is available
	# Returns True if available
	# Returns False if not available (already in database)
	def check_username( self, username ):
		if self.retrieve("select id from Users where name=?", (username, )):
			return False
		else:
			return True

	def get_tournaments( self, tournamentname = '' ):
		if tournamentname:
			return self.retrieve("select * from Tournaments where name=?", (tournamentname, ))
		else:
			return self.retrieve("select * from Tournaments")

	def get_bot_tournaments( self, t_id, bot_id ):
		return self.retrieve("select * from Tourn_Entries where tourn_id=? AND bot_id=?", (t_id, bot_id))

	def get_kill_client( self ):
		sql = "select * from kill_client"
		return self.retrieve(sql)

	def get_player_lastseen( self, t_id, bot_id ):
		return self.retrieve("select lastseen from Tourn_Entries where tourn_id=? AND bot_id=?", (t_id, name))

	def get_player( self, t_id, botname ):
		sql = "select * from Tourn_Entries AS e INNER JOIN Bots AS b on e.bot_id=b.bot_id where e.tourn_id=? AND b.name=?"
		return self.retrieve( sql, (t_id, botname) )

	#### WRITE ####

	def add_replay( self, t_id, id, txt ):
		#~ data = txt
		data = buffer(zlib.compress(txt))
		self.update("insert into Tourn_Replays values(?,?)", (id, t_id, data) )
		
	def add_game( self, t_id, i, map, turns, draws, players ):
		self.update("insert into Tourn_Games values(?,?,?,?,?,?)", (i, t_id, players, self.now(), map, turns, draws))
		
	def add_tournament( self, t_id, username, tournamentname, password =''):
		self.update("insert into Tournaments values(?,?,?,?,?,?)", (None, tournamentname, username, password, self.now(), self.now()))
	
	def add_user( self, name, password, email ):
		self.update("insert into Users values(?,?,?,?)", (None, name, password, email))

	def enroll_bot( self, u_id, bot_id, t_id ):
		self.update("insert into Tourn_Entries values(?,?,?,?)",
			(None, t_id, b_id, self.now()))

	def add_bot( self, username, botname, language ):
		u_id = self.retrieve("select id from Users where name=?", (username, ))
		self.update("insert into Bots values(?,?,?,?)", (None, u_id[0], botname, language))

	def terminate_bot( self, botname ):
		self.update("insert into kill_client values('%s');" % botname)

	def delete_player( self, name ):
		self.update("insert into kill_client values('%s');" % name)

	def delete_kill_name( self, name ):
		self.update("delete from kill_client where name = '%s';" % name)

	def update_player_skill( self, t_id, botname, skill, mu, sig ):
		self.update_defered("update Tourn_Entries as e INNER JOIN Bots as b set ngames=ngames+1, lastseen=?, skill=?, mu=?, sigma=? where e.tourn_id=? AND b.name=?",
			(self.now(), skill, mu, sig, t_id, botname))

	def update_player_status( self, t_id, bot_id, status ):
		self.update_defered("update Tourn_Entries set status=? where tourn_id=? bot_id=?", (status, t_id, bot_id))

	## needs a final commit() 
	def update_player_rank( self, t_id, bot_id, rank ):
		self.update_defered("update Tourn_entries set rank=? where tourn_id=? bot_id=?", (rank, t_id, bot_id))
		
	#~ def get_opts( self, opts ):
		#~ r = self.retrieve( "select * from opts" )
		#~ if r and len(r)==1:
			#~ for i,k in enumerate(r[0].keys()):
				#~ opts[ k ] = r[0][i]
				