#!/usr/bin/env python3
# -*- coding: utf-8 -*-


# Author: MrErwan,
# Version:    0.0.1: alpha...


"""
<plugin key="RL-G-EMeter" name="Ronelabs - General E-Meter plugin" author="Ronelabs" version="0.0.2" externallink="https://ronelabs.com">
    <description>
        <h2>General Energy Meter</h2><br/>
        Easily implement in Domoticz a General Energy Meter based on several ones<br/>
        <h3>Set-up and Configuration</h3>
    </description>
    <params>
        <param field="Username" label="Cons E-Meter (CSV List of idx)" width="400px" required="true" default=""/>

        <param field="Mode6" label="Logging Level" width="200px">
            <options>
                <option label="Normal" value="Normal"  default="true"/>
                <option label="Verbose" value="Verbose"/>
                <option label="Debug - Python Only" value="2"/>
                <option label="Debug - Basic" value="62"/>
                <option label="Debug - Basic+Messages" value="126"/>
                <option label="Debug - Connections Only" value="16"/>
                <option label="Debug - Connections+Queue" value="144"/>
                <option label="Debug - All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""

import json
import math
import urllib
import urllib.parse as parse
import urllib.request as request
import time
from datetime import datetime, timedelta
import math
import base64
import itertools
import subprocess
import os
import subprocess as sp
from typing import Any

import Domoticz
import requests
from distutils.version import LooseVersion

try:
    from Domoticz import Devices, Images, Parameters, Settings
except ImportError:
    pass



class deviceparam:

    def __init__(self, unit, nvalue, svalue):
        self.unit = unit
        self.nvalue = nvalue
        self.svalue = svalue
        self.debug = False


class BasePlugin:

    def __init__(self):
        self.debug = False
        self.EnergyConsMeter = []
        self.EnergyCons = 0
        self.TodayEnergyCons = 0
        self.LastTime = time.time()
        self.PLUGINstarteddtime = datetime.now()
        self.InternalsDefaults = {
            'V_TodayEnergyCons': 0}  # defaut
        self.Internals = self.InternalsDefaults.copy()
        return

    def onStart(self):
        Domoticz.Log("onStart called")
        # setup the appropriate logging level
        try:
            debuglevel = int(Parameters["Mode6"])
        except ValueError:
            debuglevel = 0
            self.loglevel = Parameters["Mode6"]
        if debuglevel != 0:
            self.debug = True
            Domoticz.Debugging(debuglevel)
            DumpConfigToLog()
            self.loglevel = "Verbose"
        else:
            self.debug = False
            Domoticz.Debugging(0)

        # create the child devices if these do not exist yet
        devicecreated = []
        # PVProd devices
        if 1 not in Devices:
            Domoticz.Device(Name="Total", Unit=1, Type=243, Subtype=29, Used=1).Create()
            devicecreated.append(deviceparam(1, 0, "0"))  # default is 0 Kwh forecast

        # if any device has been created in onStart(), now is time to update its defaults
        for device in devicecreated:
            Devices[device.unit].Update(nValue=device.nvalue, sValue=device.svalue)

        # build lists of idx widget of CAC221
        self.EnergyConsMeter = parseCSV(Parameters["Username"])
        Domoticz.Debug("EnergyConsMeter = {}".format(self.EnergyConsMeter))

        # reset time info when starting the plugin.
        self.PLUGINstarteddtime = datetime.now()

        # Set domoticz heartbeat to 20 s (onheattbeat() will be called every 20 )
        Domoticz.Heartbeat(20)

        # update E MEters
        self.readCons()

        # creating user variable if doesn't exist or update it
        self.getUserVar()

    def onStop(self):
        Domoticz.Log("onStop called")
        Domoticz.Debugging(0)

    def onCommand(self, Unit, Command, Level, Color):
        Domoticz.Log( "onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")


        # HEARTBEAT PVProd PART  ---------------------------------------------------

        # Recup user variables
        self.TodayEnergyCons = self.Internals['V_TodayEnergyCons']

        # update E Meters
        self.readCons()

    # UPDATING DEVICES ------------------------------------------------------------------------------------------------

        strValue1 = str(self.EnergyCons) + ";" + str(self.TodayEnergyCons)
        Devices[1].Update(nValue=0, sValue=strValue1, TimedOut=0)  # update the dummy device showing the current value
        self.WriteLog("Updating widget and user variables")
        # modif des users variable
        self.Internals['V_self.TodayEnergyCons'] = self.TodayEnergyCons
        self.saveUserVar()  # update user variables with latest values

    # OTHER DEF -------------------------------------------------------------------------------------------------------

    def readCons(self):
        Domoticz.Debug("readCons called")
        # fetch all the devices from the API and scan for sensors
        noerror = True
        listinWatt = []
        listinwH = []
        listinTodaywH = []
        devicesAPI = DomoticzAPI("type=command&param=getdevices&filter=utility&used=true&order=Name")
        if devicesAPI:
            for device in devicesAPI["result"]:  # parse the devices for temperature sensors
                idx = int(device["idx"])
                if idx in self.EnergyConsMeter:
                    if "Usage" in device:
                        Domoticz.Debug("device: {}-{} = {}".format(device["idx"], device["Name"], device["Usage"]))
                        texte = (device["Usage"])
                        valeur = texte.replace("Watt", "").strip()
                        listinWatt.append(int(valeur))
                        texte2 = (device["Data"])
                        valeur2 = texte2.replace("kWh", "").strip()
                        listinwH.append(int(float(valeur2)*1000))
                        texte3 = (device["CounterToday"])
                        valeur3 = texte3.replace("kWh", "").strip()
                        listinTodaywH.append(int(float(valeur3) * 1000))
                    else:
                        Domoticz.Error("device: {}-{} is not a E Meter sensor".format(device["idx"], device["Name"]))

        # calculate the total instant power
        nbWatt = len(listinWatt)
        if nbWatt > 0:
            self.EnergyCons = round(sum(listinWatt))
        else:
            Domoticz.Debug("No E Meter General cons found... ")
            noerror = False
        # calculate the total power
        nbKwh = len(listinwH)
        if nbKwh > 0:
            self.TodayEnergyCons = round(sum(listinwH))
        else:
            Domoticz.Debug("No E Meter General cons found... ")
            noerror = False

        Domoticz.Debug("E Meter General cons calculated value is = {}w, and {}wh".format(self.EnergyCons,self.TodayEnergyCons))
        return noerror


# User variable  ---------------------------------------------------

    def getUserVar(self):
        Domoticz.Debug("Get UserVariable called")
        variables = DomoticzAPI("type=command&param=getuservariables")
        if variables:
            # there is a valid response from the API but we do not know if our variable exists yet
            novar = True
            varname = Parameters["Name"] + "-InternalVariables"
            valuestring = ""
            if "result" in variables:
                for variable in variables["result"]:
                    if variable["Name"] == varname:
                        valuestring = variable["Value"]
                        novar = False
                        Domoticz.Status("UserVariable found and loaded")
                        break
            if novar:
                # create user variable since it does not exist
                Domoticz.Debug("User Variable {} does not exist. Creation requested".format(varname), "Verbose")

                # check for Domoticz version:
                # there is a breaking change on dzvents_version 2.4.9, API was changed from 'saveuservariable' to 'adduservariable'
                # using 'saveuservariable' on latest versions returns a "status = 'ERR'" error

                # get a status of the actual running Domoticz instance, set the parameter accordigly
                parameter = "saveuservariable"
                domoticzInfo = DomoticzAPI("type=command&param=getversion")
                if domoticzInfo is None:
                    Domoticz.Error("Unable to fetch Domoticz info... unable to determine version")
                else:
                    if domoticzInfo and LooseVersion(domoticzInfo["dzvents_version"]) >= LooseVersion("2.4.9"):
                        Domoticz.Debug("Use 'adduservariable' instead of 'saveuservariable'", "Verbose")
                        parameter = "adduservariable"

                # actually calling Domoticz API
                DomoticzAPI("type=command&param={}&vname={}&vtype=2&vvalue={}".format(parameter, varname, str(self.InternalsDefaults)))
                self.Internals = self.InternalsDefaults.copy()  # we re-initialize the internal variables
                Domoticz.Status("UserVariable Created !!!")
            else:
                try:
                    self.Internals.update(eval(valuestring))
                    Domoticz.Status("UserVariable updated")
                except:
                    self.Internals = self.InternalsDefaults.copy()
                    Domoticz.Status("UserVariable are corrupted - reset")
                return
        else:
            Domoticz.Error("Cannot read the uservariable holding the persistent variables")
            self.Internals = self.InternalsDefaults.copy()

    def saveUserVar(self):
        Domoticz.Debug("Save UserVariable called")
        varname = Parameters["Name"] + "-InternalVariables"
        DomoticzAPI("type=command&param=updateuservariable&vname={}&vtype=2&vvalue={}".format(varname, str(self.Internals)))

# Write Log  ---------------------------------------------------

    def WriteLog(self, message, level="Normal"):

        if self.loglevel == "Verbose" and level == "Verbose":
            Domoticz.Log(message)
        elif level == "Normal":
            Domoticz.Log(message)


# Plugin functions ---------------------------------------------------

global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()


# Plugin utility functions ---------------------------------------------------

def parseCSV(strCSV):
    listvals = []
    for value in strCSV.split(","):
        try:
            val = int(value)
            listvals.append(val)
        except ValueError:
            try:
                val = float(value)
                listvals.append(val)
            except ValueError:
                Domoticz.Error(f"Skipping non-numeric value: {value}")
    return listvals

def DomoticzAPI(APICall):
    resultJson = None
    url = f"http://127.0.0.1:8080/json.htm?{parse.quote(APICall, safe='&=')}"

    try:
        Domoticz.Debug(f"Domoticz API request: {url}")
        req = request.Request(url)
        response = request.urlopen(req)

        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            if resultJson.get("status") != "OK":
                Domoticz.Error(f"Domoticz API returned an error: status = {resultJson.get('status')}")
                resultJson = None
        else:
            Domoticz.Error(f"Domoticz API: HTTP error = {response.status}")

    except urllib.error.HTTPError as e:
        Domoticz.Error(f"HTTP error calling '{url}': {e}")

    except urllib.error.URLError as e:
        Domoticz.Error(f"URL error calling '{url}': {e}")

    except json.JSONDecodeError as e:
        Domoticz.Error(f"JSON decoding error: {e}")

    except Exception as e:
        Domoticz.Error(f"Error calling '{url}': {e}")

    return resultJson



# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return
