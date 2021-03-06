import json
import importlib
import sys

import enaml
from atom.api import (Atom, Str, List, Dict, Property, Typed, Unicode, Coerced,
                      Int, Callable)
from enaml.qt.qt_application import QtApplication

from .Instrument import Instrument
from . import MicrowaveSources
from . import AWGs
from JSONLibraryUtils import FileWatcher, LibraryCoders

from DictManager import DictManager

from . import Digitizers, Analysers, DCSources, Attenuators

from . plugins import find_plugins

newOtherInstrs = [Digitizers.AlazarATS9870, Digitizers.X6, Analysers.HP71000,
                  Analysers.SpectrumAnalyzer, DCSources.YokoGS200,
                  Attenuators.DigitalAttenuator]

plugins = find_plugins(Digitizers.Digitizer, verbose=False)
for plugin in plugins:
    newOtherInstrs.append(plugin)
    globals().update({plugin.__name__: plugin})
    print("Registered Digitizer Driver {}".format(plugin.__name__))


class AWGDictManager(DictManager):
    """
    Specialization of DictManager for AWGs to support auto populating channels.
    """
    populate_physical_channels = Callable()

    def __init__(self, auto_populate_channels=None, *args, **kwargs):
        super(AWGDictManager, self).__init__(*args, **kwargs)

    def add_item(self, parent):
        """
        Create a new item dialog window and handle the result
        """
        with enaml.imports():
            from widgets.dialogs import AddAWGDialog
        dialogBox = AddAWGDialog(
            parent,
            modelNames=[i.__name__ for i in self.possibleItems],
            objText="AWG")
        dialogBox.exec_()
        if dialogBox.result:
            if dialogBox.newLabel not in self.itemDict.keys():
                self.itemDict[dialogBox.newLabel] = self.possibleItems[
                    dialogBox.newModelNum](label=dialogBox.newLabel)
                self.displayList.append(dialogBox.newLabel)
                if dialogBox.auto_populate_channels and self.populate_physical_channels is not None:
                    self.populate_physical_channels(
                        [self.itemDict[dialogBox.newLabel]])
            else:
                print("WARNING: Can't use duplicate label %s" %
                      dialogBox.newLabel)


class InstrumentLibrary(Atom):
    #All the instruments are stored as a dictionary keyed of the instrument name
    instrDict = Dict()
    libFile = Str().tag(transient=True)

    #Some helpers to manage types of instruments
    AWGs = Typed(DictManager)
    markedInstrs = Typed(DictManager)
    sources = Typed(DictManager)
    others = Typed(DictManager)
    version = Int(3)

    fileWatcher = Typed(FileWatcher.LibraryFileWatcher)

    def __init__(self, **kwargs):
        super(InstrumentLibrary, self).__init__(**kwargs)
        self.load_from_library()
        if self.libFile:
            self.fileWatcher = FileWatcher.LibraryFileWatcher(
                self.libFile, self.update_from_file)

        #Setup the dictionary managers for the different instrument types
        self.AWGs = AWGDictManager(
            itemDict=self.instrDict,
            displayFilter=lambda x: isinstance(x, AWGs.AWG),
            possibleItems=AWGs.AWGList)

        self.sources = DictManager(
            itemDict=self.instrDict,
            displayFilter=lambda x: isinstance(x, MicrowaveSources.MicrowaveSource),
            possibleItems=MicrowaveSources.MicrowaveSourceList)

        self.others = DictManager(
            itemDict=self.instrDict,
            displayFilter=lambda x: not isinstance(x, AWGs.AWG) and not isinstance(x, MicrowaveSources.MicrowaveSource),
            possibleItems=newOtherInstrs)

        # To enable routing physical marker channels to more generic devices
        self.markedInstrs = DictManager(
            itemDict=self.instrDict,
            displayFilter=lambda x: not isinstance(x, AWGs.AWG) and hasattr(x, 'takes_marker') and x.takes_marker,
            possibleItems=newOtherInstrs)

    #Overload [] to allow direct pulling out of an instrument
    def __getitem__(self, instrName):
        return self.instrDict[instrName]

    def __contains__(self, key):
        return key in self.instrDict

    def write_to_file(self, fileName=None):
        libFileName = fileName if fileName != None else self.libFile
        if self.libFile:
            #Pause the file watcher to stop circular updating insanity
            if self.fileWatcher:
                self.fileWatcher.pause()

                if libFileName:
                    with open(libFileName, 'w') as FID:
                        json.dump(self,
                                  FID,
                                  cls=LibraryCoders.LibraryEncoder,
                                  indent=2,
                                  sort_keys=True)

            if self.fileWatcher:
                self.fileWatcher.resume()

    def load_from_library(self):
        if self.libFile:
            try:
                with open(self.libFile, 'r') as FID:
                    tmpLib = json.load(FID, cls=LibraryCoders.LibraryDecoder)
                    if isinstance(tmpLib, InstrumentLibrary):
                        self.instrDict.update(tmpLib.instrDict)
                        # grab library version
                        self.version = tmpLib.version
            except IOError:
                print('No instrument library found')
            except ValueError:
                print('Failed to load instrument library')

    def update_from_file(self):
        """
        Only update relevant parameters
        Helps avoid stale references by replacing whole channel objects as in load_from_library
        and the overhead of recreating everything.
        """
        if self.libFile:
            with open(self.libFile, 'r') as FID:
                try:
                    allParams = json.load(FID)['instrDict']
                except ValueError:
                    print(
                        'Failed to update instrument library from file.  Probably just half-written.'
                    )
                    return

                # update and add new items
                for instrName, instrParams in allParams.items():
                    # Re-encode the strings as ascii (this should go away in Python 3)
                    if sys.version_info[0] < 3:
                        instrParams = {k.encode('ascii'): v
                                       for k, v in instrParams.items()}
                    # update
                    if instrName in self.instrDict:
                        self.instrDict[instrName].update_from_jsondict(
                            instrParams)
                    else:
                        # load class from name and update from json
                        className = instrParams['x__class__']
                        moduleName = instrParams['x__module__']

                        mod = importlib.import_module(moduleName)
                        cls = getattr(mod, className)
                        self.instrDict[instrName] = cls()
                        self.instrDict[instrName].update_from_jsondict(
                            instrParams)

                # delete removed items
                for instrName in self.instrDict.keys():
                    if instrName not in allParams:
                        del self.instrDict[instrName]

    def json_encode(self, matlabCompatible=False):
        #When serializing for matlab return only enabled instruments, otherwise all
        if matlabCompatible:
            return {label: instr
                    for label, instr in self.instrDict.items()
                    if instr.enabled}
        else:
            return {
                "instrDict": {label: instr
                              for label, instr in self.instrDict.items()},
                "version": self.version
            }


if __name__ == '__main__':

    from MicrowaveSources import AgilentN5183A
    instrLib = InstrumentLibrary(
        instrDict={'Agilent1': AgilentN5183A(label='Agilent1'),
                   'Agilent2': AgilentN5183A(label='Agilent2')})
    with enaml.imports():
        from InstrumentManagerView import InstrumentManagerWindow

    app = QtApplication()
    view = InstrumentManagerWindow(instrLib=instrLib)
    view.show()
    app.start()
