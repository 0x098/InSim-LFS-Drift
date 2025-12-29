import os
import socket
import struct
import math
import sys
import threading
import time
import sqlite3
import insimconfig as CFG
import isptranslation as T
import carlist as N

BUFFER_SIZE = 2048
INSIM_VERSION = 9

# currently used(?) packets
ISP_ISI = 1 # InSim Init
ISP_VER = 2 # Version info
ISP_TINY = 3 # Multi purpose
ISP_STA = 5 # State info
ISP_MSO = 11 # Message out
ISP_MST = 13 # type message or /command
ISP_MTC = 14 # message to connection
ISP_VTN = 16 # vote notification
ISP_RST = 17 # race start
ISP_NCN = 18 # new connection
ISP_NPL = 21 # new player joined race
ISP_PLL = 23 # player leave
ISP_LAP = 24 # lap
ISP_SPX = 25 # lap + split
ISP_PFL = 33 # player flags ( help flags )
ISP_REO = 36 # reorder by connection id
ISP_MCI = 38 # multi car info
ISP_MSL = 40 # message to local computer
ISP_CRS = 41 # car reset 
ISP_BFN = 42 # delete button / receive btn req
ISP_AXI = 43 # autocross lay info
ISP_BTN = 45 # show btn on local/remote scr
ISP_OBH = 51 # object collision with car
ISP_AXM = 54 # layout changes if set to clear
ISP_JRR = 58 # reply to join req
ISP_UCO = 59 # insim checkpoint / cicle
ISP_CSC = 63 # car state change
ISP_CIM = 64 # conn interface mode

IS_TINY_SIZE = 4//4
IS_SMALL_SIZE = 8//4
ISP_CPP_SIZE = 32//4
ISP_REO_SIZE = 44//4
ISP_BFN_SIZE = 8//4
ISP_RIP_SIZE = 80//4
ISP_SSH_SIZE = 40//4
ISP_AXM_SIZE = 8//4 # + 8*NumberOfObjectsYoureSending//8
ISP_MAL_SIZE = 8//4 # + 4*NumberOfMods//4
ISP_PLH_SIZE = 4//4 # + 4*PlayerHandiCaps//4
ISP_IPB_SIZE = 8//4 # + 4*NumberOfIPBans//4

ISP_ISI_SIZE = 44//4
ISP_SCH_SIZE = 8//4
ISP_SFP_SIZE = 8//4
ISP_SCC_SIZE = 8//4
ISP_MST_SIZE = 68//4
ISP_MTC_SIZE = 8//4 # + TEXT_SIZE "ABC\0" = 1 "ABCDEFG\0" = 2 -> ceil(len(str+1) // 4)
ISP_MOD_SIZE = 20//4
ISP_MSX_SIZE = 100//4
ISP_MSL_SIZE = 132//4
ISP_BTN_SIZE = 12//4 # + TEXT_SIZE ^
ISP_PLC_SIZE = 12//4
ISP_HCP_SIZE = 68//4
ISP_JRR_SIZE = 16//4
ISP_OCO_SIZE = 8//4
ISP_TTC_SIZE = 8//4

TINY_NONE = 0 # keep-alive(heartbeat) packet
TINY_VER = 1 # get version
TINY_CLOSE = 2 # close insim
TINY_PING = 3 # ping req / heartbeat
TINY_REPLY = 4 # ping reply
TINY_VTC = 5 # game vote cancel
TINY_NCN = 13 # get NCN (new conncetion packet) for all connection
TINY_NPL = 14 # get all players
TINY_NCI = 23 # get NCI for all players (unused atm)
TINY_AXI = 20 # get layout into etc

heatMapColStr = [b"^7", b"^4", b"^6", b"^2", b"^3", b"^1", b"^5", b"^0"]
HEATMAPLEN = len(heatMapColStr)
COLPERANGLE = CFG.MAX_DRIFT_ANGLE / HEATMAPLEN

#struct.pack
#// char    1-byte character -> c (1)
#// byte    1-byte unsigned integer -> B (1)
#// word    2-byte unsigned integer -> unsigned short -> H (2)
#// short   2-byte signed integer -> short -> h (2)
#// unsigned  4-byte unsigned integer -> I (4)
#// int     4-byte signed integer -> i (4)
#// float   4-byte float -> f (4)


plidToUcid = {} # player unique id to user connection unique id
ucidToPlid = {} # user connection unique id to player unique id
plidToUName = {} # pluid to nicknames
plidToNName = {} # pluid to actual global lfs user identifiers
plidToCarName = {}

DRIFT_BUTTON_SCR = 0
DRIFT_BUTTON_DEG = 1
DRIFT_BUTTON_KPH = 2

layoutData = {"id" : "<empty>"}

IsLocal = 0

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
  s.connect(("8.8.8.8", 80))
  rh = socket.gethostbyname(CFG.REMOTE_HOST)
  if rh == s.getsockname()[0] or rh == "127.0.0.1":
    IsLocal = 1

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

def sendTiny(REQI, TINY_TYPE):
  sock.send(struct.pack("BBBB",
    IS_TINY_SIZE,
    ISP_TINY,
    REQI,
    TINY_TYPE)) # TINY_NCN & TINY_NPL

def sendCommand(command):
  sock.send(struct.pack("BBBB63sB",
    ISP_MST_SIZE,
    ISP_MST,
    0,0,
    command.encode("cp1252"),0))

_heartbeatbytes = b'\x01\x03\x00\x00'
def sendHeartbeat():
  sock.send(_heartbeatbytes)


# SINCE: sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread. The object was created in thread id 42576 and this is thread id 4392.

DB = []
DBOUT = []
DB_INSERT = 0
DB_SELECT_ONE = 1
DB_SELECT_MANY = 2


stateMachine = {}

stateMachine["dbMachine"] = 0
RTDBQ = []
def sqfat(stateMachine):
  sqlC = sqlite3.connect(CFG.INSIM_DB_PATH)
  cursor = sqlC.cursor()
  cursor.execute('''
  create table if not exists hiScores (
    id integer primary key autoincrement,
    userid text not null,
    layoutid text not null,
    score integer not null,
    displayname text not null,
    laptime real not null,
    carid text not null,
    unixtime timestamp default current_timestamp
    )
    ''')

  sqlC.commit()
  while stateMachine["dbMachine"] == 0:
    queries = len(DB)
    if queries > 0: # actions that request no output # 1 at a time cuz hurr durr
      nextsleep = 0.1
      # funny cuz if 
      cursor.execute(DB[0][1], DB[0][2]) # run regardless lol
      if DB[0][0] == DB_INSERT:
        if queries > 1:
          if DB[1][0] != DB_INSERT:
            sqlC.commit()
            print("<db>committing...")
          else:
            nextsleep = 0.01
        #if not DB[1][0] == DB_INSERT: # peek if next one is also an insert. if not then commit.
      elif DB[0][0] == DB_SELECT_ONE:
        DBOUT.append(cursor.fetchone()[0]) # sane
      elif DB[0][0] == DB_SELECT_MANY:
        DBOUT.append(cursor.fetchall()) # crazy
      DB.pop(0)
      time.sleep(nextsleep)
    time.sleep(0.01)
    if len(RTDBQ) > 0:
      try:
        cursor.execute(RTDBQ[0])
        RTDBQ.pop(0)
        res = cursor.fetchall()
        print(res)
      except Exception as e:
        print("db >> error:", e)
  print("exiting db")
  sqlC.commit()
  sqlC.close()
  stateMachine["dbMachine"] = 2 # dead state
  print("db state 2")

dbthr = threading.Thread(target=sqfat, args=(stateMachine,))
dbthr.start()


def addlap2db(userid, layoutid, score, displayname, laptime, carid, callback=print):
  DB.append((
    DB_INSERT,
    "insert into hiScores (userid,layoutid,score,displayname,laptime,carid) values (?,?,?,?,?,?)", 
    (userid,layoutid,score,displayname,laptime,carid),
    callback
  ))

MainThreadID = threading.get_ident()

def db(query):
  if threading.get_ident() == MainThreadID:
    RTDBQ.append(query)
  else:
    print("db >> invalid thread id. unalive yourself, now!")

__dat = b''
__fc = 1

print("IsLocal:", IsLocal)

while __dat == b'':
  if __fc:
    __fc = 0
  else:
    print("retrying...")
  sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  sock.connect((CFG.REMOTE_HOST, CFG.REMOTE_PORT))

  ISI = struct.pack('BBBBHHBcH16s16s', # insim init
    ISP_ISI_SIZE,   # Size
    ISP_ISI,     # Type
    1,       # ReqI
    0,       # Zero
    
    0,       # UDPPort
    32 + 4 * IsLocal + 128 + 1024,   # Flags

    INSIM_VERSION, # Sp0
    b'S',     # Prefix
    50,     # Interval

    CFG.REMOTE_INSIM_PASSWORD,
    CFG.REMOTE_INSIM_USERNAME)

  sock.send(ISI)

  __dat = sock.recv(BUFFER_SIZE)
  time.sleep( 1 ) # wait a sec



OldPos = 0
NewPos = 1
ScoVel = 2
ScoAng = 3
Heading = 4
LocVel = 5
Score = 6
LastLapTime = 7
Tracking = 8
OldScore = 9
PenaltiesSum = 10
LapTimeStamp = 11
LastElement = 12

Scores = []

PacketBuffer = []

stateMachine["heartBeat"] = time.time()

for a in range(LastElement):
  Scores.append({})

X, Y = 0, 1

def normalize(x, y):
  length = (x * x + y * y) ** 0.5
  if length == 0:
    return 0, 0
  return x / length, y / length


def resetCar(plid, doPrint=True):
  Scores[OldPos][plid] = [0,0]
  Scores[NewPos][plid] = [0,0]
  Scores[ScoVel][plid] = [0,0]
  Scores[Heading][plid] = [0,0]
  Scores[LocVel][plid] = [0,0]
  Scores[LastLapTime][plid] = 0
  Scores[ScoAng][plid] = 0
  Scores[Score][plid] = 0
  Scores[Tracking][plid] = False
  Scores[OldScore][plid] = 0
  Scores[PenaltiesSum][plid] = 0
  if doPrint:
    print("Car reset:", plid)

carobjids = ["dir", "heading", "speed", "zbyte", "x", "y"]
def unpackCarObj(bytes):
  return dict(zip(carobjids, struct.unpack("4B2h", bytes)))

def startTrackingCar(plid, doPrint=True):
  if not Scores[Tracking][plid]:
    Scores[Tracking][plid] = True
    if not plid in Scores[LapTimeStamp]:
      Scores[LapTimeStamp][plid] = time.time()
    print("Tracking:", plid)
    sock.send(struct.pack("BBBBBBBBBBBB4s",
      ISP_BTN_SIZE + 1,
      ISP_BTN,
      1, #reqi
      plidToUcid[plid],

      0, #buttonid
      0, #extra flags Inst
      32, #button style (color)
      0, #max chars user can type into the btn

      90, #lef
      50, #top
      20, #wif
      10, #hyt
      b"^60",
      ))
    print("Sending bt")
    sock.send(struct.pack("BBBBBBBBBBBB12s", # send button to see that stuff
      ISP_BTN_SIZE + 3,
      ISP_BTN,
      1, #reqi
      plidToUcid[plid],

      1, #buttonid
      0, #extra flags Inst
      32+128, #button style (color)
      0, #max chars user can type into the btn

      90, #left
      60, #top
      10, #width
      5, #hyt
      b"^7" + str("0°").encode("cp1252")
      ))
    sock.send(struct.pack("BBBBBBBBBBBB12s",
      ISP_BTN_SIZE + 3,
      ISP_BTN,
      1, #reqi
      plidToUcid[plid],

      2, #buttonid
      0, #extra flags Inst
      32+64, #button style (color)
      0, #max chars user can type into the btn

      100, #left
      60, #top
      10, #width
      5, #hyt
      b"^7" + str("0kph").encode("cp1252")
      ))



def netReceiver(pbr, stateMachine):
  stateMachine["netReceiver"] = 1
  while stateMachine["netReceiver"] == 1:
    data = sock.recv(BUFFER_SIZE)
    if not data:
      break
    pbr.insert(0, data)
  stateMachine["netReceiver"] = 0

receiverThread = threading.Thread(target=netReceiver, args=(PacketBuffer, stateMachine))
receiverThread.start()

packetHandler = [None] * 128

def ISP_VER_H(data, size):
  version = data[4 : 4+8].decode("utf-8").replace("\0","")
  product = data[4+8 : 4+8+6].decode("utf-8").replace("\0","")
  insimver = data[4+8+6]
  print(f"<== [{version} : {product}] InSimVer: {insimver} IsLocal:{IsLocal} ==>")
packetHandler[ISP_VER] = ISP_VER_H

def ISP_TINY_H(data, size):
  # stateMachine["heartBeat"]
  if len(data) == 4 and data[3] == TINY_NONE:
    sendHeartbeat()
    stateMachine["heartBeat"] = time.time() - 1
  elif time.time() - stateMachine["heartBeat"] > 30:
    stateMachine["heartBeat"] = time.time() - 1
    sendHeartbeat()
    print("send emergency heartbeat")
packetHandler[ISP_TINY] = ISP_TINY_H

def ISP_MCI_H(data, size): # multi-car info
  # bSize bType bReqI bNumC CompCarInfo(size b28)
  bNumC = data[3]
  # wNode:0:1, wLap:2:3, bPlayerID:4, bPositionInRace:5, bInfo:6, bSpacer:7
  # iX:8:12, iY:12:16, iZ:16:20
  # wSpeed:21:22, wDirection:23:24, wHeading:25:26, sAngVel:27:28
  for nThCar in range(bNumC):
    # print(nThCar)
    carData = data[4 + (nThCar * 28):]
    plid = carData[4]
    if not plid in plidToUcid:
      if IsLocal: # TODO this but MP
        sendCommand("/spec")
    if not plid in Scores[Tracking]:
      print("resetting", plid)
      resetCar(plid, False)
    if not Scores[Tracking][plid]:
      continue
    x, y, _, speed, dir, heading, angvel = struct.unpack("iiiHHHh", carData[8 : 28])
    dir /= 32768 / 180 
    heading /= 32768 / 180
    angvel /= 16384
    speed /= 32768 / 360
    x /= 65536
    y /= 65536

    Scores[OldPos][plid][X] = Scores[NewPos][plid][X]
    Scores[OldPos][plid][Y] = Scores[NewPos][plid][Y]

    Scores[NewPos][plid][X] = x
    Scores[NewPos][plid][Y] = y

    Scores[ScoVel][plid][X] = Scores[NewPos][plid][X] - Scores[OldPos][plid][X]
    Scores[ScoVel][plid][Y] = Scores[NewPos][plid][Y] - Scores[OldPos][plid][Y]

    nX, nY = normalize(Scores[ScoVel][plid][X], Scores[ScoVel][plid][Y])

    headingInRads = math.radians(dir)
    Scores[Heading][plid][X] = math.cos(headingInRads)
    Scores[Heading][plid][Y] = math.sin(headingInRads)

    dirRightX = -Scores[Heading][plid][Y]
    dirRightY = Scores[Heading][plid][X]
    
    Scores[LocVel][plid][X] = nX * Scores[Heading][plid][X] + nY * Scores[Heading][plid][Y]
    Scores[LocVel][plid][Y] = nX * dirRightX + nY * dirRightY
    
    diff = dir - heading
    if diff > 180:
      diff -= 360 
    elif diff < -180:
      diff += 360

    diff = diff * min(1, max(0, (speed - 10) / 5))

    sock.send(struct.pack("BBBBBBBBBBBB12s",
      ISP_BTN_SIZE + 3, ISP_BTN, 1, plidToUcid[plid],

      DRIFT_BUTTON_DEG, #buttonid
      0, #extra flags Inst
      32+128, #button style (color)
      0, #max chars user can type into the btn

      90, 60, 10, 5, #hyt
      heatMapColStr[ max(0, min(HEATMAPLEN-1, int( abs(diff) / COLPERANGLE ) - 1 ) ) ] + (str(abs(int(diff))) + "°").encode("cp1252")
      ))
    sock.send(struct.pack("BBBBBBBBBBBB12s",
      ISP_BTN_SIZE + 3, ISP_BTN, 1, plidToUcid[plid],

      DRIFT_BUTTON_KPH, #buttonid
      0, #extra flags Inst
      32+64, #button style (color)
      0, #max chars user can type into the btn

      100, 60, 10, 5, #left top wif hyt
      heatMapColStr[ max(0, min(HEATMAPLEN-1, int(speed/22.25))) ] + (str(int(speed)) + "kph").encode("cp1252")
      ))
    
    
    if abs(diff) < 10:
      continue
    if speed < 15:
      continue
    if ((-Scores[LocVel][plid][X] > 0 and diff > 0) or (-Scores[LocVel][plid][X] < 0 and diff < 0)) and abs(diff) < CFG.MAX_DRIFT_ANGLE:
      Scores[Score][plid] = Scores[Score][plid] + (abs(diff) * (speed ** 1.25)) * 0.0125
      # print(f"{Scores[Score][plid]:.1f} {abs(diff):.1f} {-Scores[LocVel][plid][X]:.5f}")
    elif abs(diff) > CFG.MAX_DRIFT_ANGLE and Scores[Score][plid] > 0:
      resetCar(plid, False)
      startTrackingCar(plid)

    # send button update if score has changed ( we do have other things that can change it )
    if Scores[OldScore][plid] != Scores[Score][plid]:
      Scores[OldScore][plid] = Scores[Score][plid]
      sock.send(struct.pack("BBBBBBBBBBBB12s",
        ISP_BTN_SIZE + 3, ISP_BTN, 1, plidToUcid[plid],

        DRIFT_BUTTON_SCR, #buttonid
        0, #extra flags Inst
        32, #button style (color)
        0, #max chars user can type into the btn

        0, 0, 0, 0, #hyt
        b"^6" + str(int(Scores[Score][plid])).encode("cp1252"),
        # constant col for score cuz we have no upper limit
        ))
packetHandler[ISP_MCI] = ISP_MCI_H

def ISP_CRS_H(data, size):
  plid = data[3]
  resetCar(plid)
packetHandler[ISP_CRS] = ISP_CRS_H

def ISP_PFL_H(data, size):
  plid = data[3]
  flags = data[4:6]
  #print(plid, ' '.join(f'{byte:08b}' for byte in flags))
  resetCar(plid)
packetHandler[ISP_PFL] = ISP_PFL_H

def ISP_UCO_H(data, size):
  plid = data[3]
  ucoaction = data[5] # should be 2
  #_, dir, heading, speed, _, x, y  = struct.unpack("IBBBBHH", data[8:20])
  if ucoaction == 2:
    if plid in plidToUcid:
      startTrackingCar(plid)
    else:
      if IsLocal: # TODO: MP FIX
        sendCommand("/spec")
packetHandler[ISP_UCO] = ISP_UCO_H

def ISP_NPL_H(data, size):
  size = data[0]
  plid = data[3]
  ucid = data[4]
  ucidToPlid[ucid] = plid
  plidToUcid[plid] = ucid
  pname, plate, carname = struct.unpack("24s8s4s", data[8:8+24+8+4])
  plidToNName[plid] = pname.decode("cp1252").replace("\0","")
  #print(carname[::-1].hex().upper()[2:])
  carname = carname[::-1].hex().upper()[2:]
  if carname in N.VALID:
    carname = N.VALID[carname]
  plidToCarName[plid] = carname
  print(f"ISP_NEWPLAYERJOIN: {size}, ucid({ucid}), plid({plid}), nname({plidToNName[plid]}), carname({carname}), plate({plate})")
packetHandler[ISP_NPL] = ISP_NPL_H

def ISP_LAP_H(data, size):
  plid = data[3]
  laptimems = struct.unpack("i",data[4:8])[0]
  #laptimems = curtime - Scores[LapTimeStamp][plid]
  if laptimems == 3600000:
    print(Scores[Score][plid], plid, "LOCAL: ", laptimems)
    curtime = time.time()
    laptimems = round( curtime - Scores[LapTimeStamp][plid] , 3 )
    Scores[LapTimeStamp][plid] = curtime # this wont be used furthermore
  else:
    laptimems = laptimems / 1000 # since 1000 = 1sec
    print(Scores[Score][plid], plid, laptimems)
  penalties = False
  penval = Scores[PenaltiesSum][plid]
  if penval == 0: 
    penalties = "0"
  elif penval > 0:
    penalties = "^2+" + str(penval) + "^7"
  else:
    penalties = "^1" + str(penval) + "^7"
  intScore = int(Scores[Score][plid])
  if plid in plidToUcid:
    ucid = plidToUcid[plid]
    nname = plidToNName[plid]
    msg = f"{nname}^7 -> {intScore} ( {penalties} ) in {laptimems}".encode("cp1252")
    if ucid == 0: # if player is host 0 == host at all time
      sock.send(struct.pack("BBBB128s",
        ISP_MSL_SIZE,
        ISP_MSL,
        0,
        0,
        msg))
      addlap2db("localhost", layoutData["id"], intScore, nname, laptimems, plidToCarName[plid])
    else:
      msglen = ( ( len(msg) + 1) // 4 ) + 1 # needed for guaranteed \0
      sock.send(struct.pack("BBBBBBBB",
        ISP_MTC_SIZE + msglen, #34,
        ISP_MTC,
        0,
        1,
        255, #receiver ucid
        0, #receiver plid
        0, #usertype
        0,
        ) + struct.pack(str(msglen) + "s", msg))
  else:
    if IsLocal:
      sendCommand("/spec")
    else:
      if plid in plidToNName:
        sendCommand(f"/spec {plidToNName[plid]}")
  

  # player not in plid list
  # addlap2db
  # add database queries here
  # we will probably never have more than ~5 queries per second unless this is rewritten to be used in multiple servers
  # this implies that the database system is also rewritten with a queue+handler system
    
  resetCar(plid)
  startTrackingCar(plid)
packetHandler[ISP_LAP] = ISP_LAP_H

def ISP_JRR_H(data, size):
  plid = data[3]
  ucid = data[4]
  ucidToPlid[ucid] = plid
  plidToUcid[plid] = ucid
packetHandler[ISP_JRR] = ISP_JRR_H

def ISP_MSO_H(data, size):
  textstart = data[7]
  #print(data)
  endpos = 128
  for i in range(128):
    if data[8+textstart+i:8+textstart+i+1] == b'\x00':
      endpos = 8+textstart+i+2
      break
  msg = data[8:endpos].decode("cp1252")
  msg = msg[:msg.find("\0")]
  if textstart:
    print(f" [{msg[:textstart-5]}]: {msg[textstart:]}")
  else:
    print("", msg.replace("^L",""))
packetHandler[ISP_MSO] = ISP_MSO_H

def ISP_PLL_H(data, size):
  plid = data[3]
  if not plid in plidToUcid:
    return
  ucid = plidToUcid[plid]
  
  sock.send(struct.pack("BBBBBBBB", # del all btn
    2,
    ISP_BFN,
    0,
    1,
    ucid,
    0,
    255,
    0))
  print("ISP_PLAYERLEAVE", ucid, plid)
packetHandler[ISP_PLL] = ISP_PLL_H

def ISP_CIM_H(data, size):
  ucid = data[3]
  mode = data[4]
  submode = data[5]
  seltyp = data[6]
  print(f"ISP_CIM: CL:{ucid}:mode -> {mode} -> {submode} -> {seltyp}")
packetHandler[ISP_CIM] = ISP_CIM_H

def ISP_STA_H(data, size):
  ingamecam = data[10]
  vplid = data[11]
  numP = data[12]
  numC = data[13]
  svstat = data[19]
  print(f"ISP_STA: igc:{ingamecam} vplid:{vplid} numPl:{numP} numCl:{numC} svStat:{svstat}")
packetHandler[ISP_STA] = ISP_STA_H

def ISP_RST_H(data, size):
  for id in Scores[Score]:
    Scores[Score][id] = 0
    print(f"resetting: {id}")
packetHandler[ISP_RST] = ISP_RST_H

def ISP_NCN_H(data, size):
  ucid = data[3]
  uname = struct.unpack("24s", data[4:4+24])[0].decode("cp1252")
  nname = struct.unpack("24s", data[4+24:4+24+24])[0].decode("cp1252")
  if sum(bytes(uname,"ascii")) == 0:
    print("no username == local")
  print(f"THIS NEEDS TO BE REDONE: ISP_NCN:, ucid({ucid}), uname({uname}), nname({nname}), data({data})")
packetHandler[ISP_NCN] = ISP_NCN_H

def ISP_AXI_H(data, size):
  layoutData["id"] = struct.unpack("32s", data[8:8+32])[0].decode("cp1252").replace("\0","")
  if layoutData["id"] == "":
    layoutData["id"] = "<empty>"
  print("ISP_AXI:", layoutData["id"])
packetHandler[ISP_AXI] = ISP_AXI_H

def ISP_REO_H(data, size):
  print("ISP_REO")
  # continue execution because mfs sent 2 in a row
packetHandler[ISP_REO] = ISP_REO_H

def ISP_SPX_H(data, size):
  splitTime, totalTime = struct.unpack("ii", data[4:12])
  print(f"split+lap: {splitTime} + {totalTime}")
packetHandler[ISP_SPX] = ISP_SPX_H

def ISP_CSC_H(data, size): # car state change
  plid = data[3]
  cscAction = data[5]
  #uintTime = struct.unpack("i", data[8:12])
  print(f"csc:{cscAction} plid:{plid}")
packetHandler[ISP_CSC] = ISP_CSC_H



def ISP_OBH_H(data, size):
  plid = data[3]
  plname = plidToNName[plid]
  index = data[size * 4 - 2]
  if index == 0:
    x, y = struct.unpack("2h", data[12:16])
    x /= 16
    y /= 16
    print(f"{plname} hit unknown object? @[ {x}, {y} ]")
  obhflags = data[size * 4 - 1]
  wasmoving = obhflags & 4
  if wasmoving:
    return
  #inorigspot = obhflags & 8
  # reverse for hitting static objects you get double penalty
  moveableobject = 0 if (obhflags & 2) == 2 else 1

  #print(f"{plname} hit: f:{obhflags} i:{index} ismoveable:{moveableobject}")
  if not plid in Scores[Tracking]:
    print("resetting", plid)
    resetCar(plid, False)
    startTrackingCar(plid)
  if not Scores[Tracking][plid]:
    return
  pen = False
  if index in CFG.OBJ_PENALTY_LIST:
    pen = CFG.OBJ_PENALTY_LIST[index]
  else:
    pen = CFG.OBJ_DEFAULT_PENALTY
  pen += ( pen * CFG.OBJ_STATIC_PENALTY_MULT * moveableobject )
  Scores[Score][plid] += pen
  if pen == 0:
    penCol = "^6"
  elif pen > 0 :
    penCol = b"^2"
  else:
    penCol = b"^1"
  sock.send(struct.pack("BBBBBBBBBBBB12s",
    ISP_BTN_SIZE + 3, ISP_BTN, 1, plidToUcid[plid],

    DRIFT_BUTTON_SCR, #buttonid
    0, #extra flags Inst
    32, #button style (color)
    0, #max chars user can type into the btn

    0, 0, 0, 0, #hyt
    penCol + str(int(Scores[Score][plid])).encode("cp1252"),
    # constant col for score cuz we have no upper limit ->> penaltied color now
    ))
  Scores[PenaltiesSum][plid] += pen

packetHandler[ISP_OBH] = ISP_OBH_H

def ISP_AXM_H(data, size):
  print("ISP_AXM:", data[5], "<empty>")
  if data[5] == 3: # PMO_CLEAR_ALL
    layoutData["id"] = "<empty>"
packetHandler[ISP_AXM] = ISP_AXM_H


stateMachine["netHandler"] = 1
def netHandler(PacketBuffer, stateMachine):
  lastPacketType = 0
  while stateMachine["netHandler"] == 1:
    if len(PacketBuffer) < 1:
      continue
    data = PacketBuffer.pop()
    rSize = len(data)
    size = data[0]
    if rSize/4 > size:
      PacketBuffer.append(data[size * 4:])
      data = data[:size * 4]
    packetType = data[1]
    if lastPacketType != packetType:
      print(f"<<sz[{size}]: type -> {T.IDTOSTR[packetType]}")
      lastPacketType = packetType
    if packetHandler[packetType]:
      packetHandler[packetType](data, size)
    else:
      if T.IDTOSTR[packetType]:
        print(f"unhandled packet type: {T.IDTOSTR[packetType]} sz:{size}({size*4}bytes)")
      else:
        print(f"unknown packet type:{packetType} sz:{size}({size * 4}bytes) d:{data}")

  stateMachine["netHandler"] = 0

handlerThread = threading.Thread(target=netHandler, args=(PacketBuffer, stateMachine))
handlerThread.start()


# sock.send(struct.pack("BBBB", IS_TINY_SIZE, ISP_TINY, 1, TINY_AXI))
sendTiny(1, TINY_AXI)
sendTiny(2, TINY_NCN)
sendTiny(3, TINY_NPL)


def quitFunc():
  try:
    # sock.send(struct.pack("BBBB", IS_TINY_SIZE,  ISP_TINY,  0,  TINY_CLOSE))
    sendTiny(0, TINY_CLOSE)
  except:
    print("couldn't send closing packet")
  # send a IS_TINY (4 bytes  bSize bType bReqI bSubT)
  stateMachine["netHandler"] = 2
  stateMachine["netReceiver"] = 2
  stateMachine["dbMachine"] = 1 # go die
  handlerThread.join()
  print("thr<nethandler>dead")
  receiverThread.join()
  print("thr<netreceiver>dead")
  sock.close()
  print("waiting for db to close")
  dbthr.join()
  print("thr<db>dead")
  exit()

def showPlFunc():
  for userconnectionid in ucidToPlid:
    plid = ucidToPlid[userconnectionid]
    uname = plidToNName[plid]
    print(f"CID : {userconnectionid} > PLID: {plid} > USERNAME: {uname}")

def helpFunc():
  es = "\n"
  es = es + "All text inputted gets executed except hotstrings (case-sens!)\n"
  es = es + "List of commands:\n"
  for str in hotStrings:
    es = es + str +" -> "+ hotStrings[str][1] + "\n"
  print(es)

def showLayout():
  print(layoutData["id"])


hotStrings = {
  "q" : [quitFunc, "quit insim"],
  "h" : [helpFunc, "show all commands"],
  "p" : [showPlFunc, "show all players"],
  "l" : [showLayout, "print current layout"],
}

helpFunc()

while True:
  try:
    val = input("")
    if val in hotStrings:
      hotStrings[val][0]()
    else:
      exec(val)
  except KeyboardInterrupt as k:
    #print("avoid keyboardinterrupt! use q !")
    quitFunc()
  except Exception as e:
    print(e)
