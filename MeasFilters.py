"""
Measurement filters
"""

from atom.api import Atom, Int, Float, List, Str, Dict, Bool, Enum, Coerced, Typed, observe, Instance
import enaml
from enaml.qt.qt_application import QtApplication
from instruments.Digitizers import ATS9870, X6
from DictManager import DictManager
import json
import sys
from JSONLibraryUtils import FileWatcher, LibraryCoders

class MeasFilter(Atom):
    label = Str()
    enabled = Bool(True)
    data_source = Str().tag(desc="Where the measurement data is pushed from.")

    def json_encode(self):
        jsonDict = self.__getstate__()
        jsonDict['x__class__'] = self.__class__.__name__
        jsonDict['x__module__'] = self.__class__.__module__
        return jsonDict

class Plotter(MeasFilter):
    label    = Str()
    enabled  = Bool(True)
    plot_mode = Enum('amp/phase', 'real/imag', 'quad').tag(desc='Filtered data scope mode.')

class WriteToHDF5(MeasFilter):
    label       = Str()
    enabled     = Bool(True)
    filename    = Str('').tag(desc='Path to file where records will be saved.')
    compression = Bool(True)

class Averager(MeasFilter):
    label   = Str()
    enabled = Bool(True)
    axis    = Str('').tag(desc='Name of the axis to average along.')

class AlazarStreamSelector(MeasFilter):
    data_source = Instance((str, ATS9870))
    channel    = Str().tag(desc="Which channel to select from the Alazar")

    def json_encode(self):
        jsonDict = super(AlazarStreamSelector, self).json_encode()

        obj = jsonDict.pop('data_source')
        if obj:
            jsonDict['data_source'] = obj.label
        return jsonDict

    def update_from_jsondict(self, jsonDict):
        jsonDict.pop('x__class__', None)
        jsonDict.pop('x__module__', None)

        #Convert the strings to ascii for Python 2
        if sys.version_info[0] < 3:
            for label,value in jsonDict.items():
                if hasattr(self, label):
                    if isinstance(value, unicode):
                        setattr(self, label, value.encode('ascii'))
                    else:
                        setattr(self, label, value)

class X6StreamSelector(MeasFilter):
    data_source                = Instance((str, X6))
    label                      = Str()
    stream_type                = Enum('Raw', 'Demodulated', 'Integrated').tag(desc='Which stream type to select.')
    if_freq                    = Float(10e6).tag(desc='IF Frequency')
    demod_kernel               = Str().tag(desc='Integration kernel vector for demod stream')
    demod_kernel_bias          = Str("").tag(desc="Kernel bias for integrated demod stream")
    raw_kernel                 = Str().tag(desc='Integration kernel vector for raw stream')
    raw_kernel_bias            = Str("").tag(desc="Kernel bias for integrated raw stream")
    threshold                  = Float(0.0).tag(desc='Qubit state decision threshold')
    threshold_invert           = Bool(False).tag(desc="Invert thresholder output")

    def json_encode(self):
        jsonDict = super(X6StreamSelector, self).json_encode()

        obj = jsonDict.pop('data_source')
        if obj:
            jsonDict['data_source'] = obj.label
        return jsonDict

    def update_from_jsondict(self, jsonDict):
        jsonDict.pop('x__class__', None)
        jsonDict.pop('x__module__', None)
        
        #Convert the strings to ascii for Python 2
        if sys.version_info[0] < 3:
            for label,value in jsonDict.items():
                if hasattr(self, label):
                    if isinstance(value, unicode):
                        setattr(self, label, value.encode('ascii'))
                    else:
                        setattr(self, label, value)

class Channelizer(MeasFilter):
    if_freq         = Float(10e6).tag(desc='The I.F. frequency for digital demodulation.')
    bandwidth      = Float(5e6).tag(desc='Low-pass filter bandwidth')
    sampling_rate  = Float(250e6).tag(desc='The sampling rate of the digitizer.')
    phase          = Float(0.0).tag(desc='Phase rotation to apply in rad.')
    decim_factor_1 = Int(1).tag(desc="First stage polyphase decimation (before multiplication with reference).")
    decim_factor_2 = Int(1).tag(desc="Second stage polyphase decimation (before IIR filter).")
    decim_factor_3 = Int(1).tag(desc="Third stage polyphase decimation (after IIR filter).")

class KernelIntegrator(MeasFilter):
    kernel        = Str('').tag(desc="Integration kernel vector.")
    bias          = Float(0.0).tag(desc="Bias after integration.")
    simple_kernel = Bool(True)
    box_car_start = Int(1)
    box_car_stop  = Int(1)
    if_freq       = Float(10e6)
    sampling_rate = Float(250e6)

class Correlator(MeasFilter):
    filters = List()

    def __init__(self, **kwargs):
        super(Correlator, self).__init__(**kwargs)
        if not self.filters:
            self.filters = [None, None]

    def json_encode(self):
        jsonDict = super(Correlator, self).json_encode()
        #For correlation filters return the filter list as a list of filter names
        filterList = jsonDict.pop('filters')
        jsonDict['filters'] = [item.label for item in filterList] if filterList else []
        jsonDict['data_source'] = ','.join(jsonDict['filters']) # correlator has mulitple data sources which are one and the same as the filter list
        return jsonDict

class StateComparator(MeasFilter):
    threshold        = Float(0.0)
    integration_time = Int(-1).tag(desc='Comparator integration time in decimated samples, use -1 for the entire record')

class MeasFilterLibrary(Atom):
    # filterDict = Dict(Str, MeasFilter)
    filterDict = Coerced(dict)
    libFile = Str().tag(transient=True)
    filterManager = Typed(DictManager)
    version = Int(1)

    fileWatcher = Typed(FileWatcher.LibraryFileWatcher)

    def __init__(self, **kwargs):
        super(MeasFilterLibrary, self).__init__(**kwargs)
        self.load_from_library()
        if self.libFile:
            self.fileWatcher = FileWatcher.LibraryFileWatcher(
                self.libFile, self.load_from_library)
        self.filterManager = DictManager(itemDict=self.filterDict, possibleItems=measFilterList)

    #Overload [] to allow direct pulling of measurement filter info
    def __getitem__(self, filterName):
        return self.filterDict[filterName]

    def write_to_file(self,fileName=None):
        libFileName = fileName if fileName != None else self.libFile

        if libFileName:
            #Pause the file watcher to stop circular updating insanity
            if self.fileWatcher:
                self.fileWatcher.pause()

            with open(libFileName, 'w') as FID:
                json.dump(self, FID, cls=LibraryCoders.LibraryEncoder, indent=2, sort_keys=True)

            if self.fileWatcher:
                self.fileWatcher.resume()

    def load_from_library(self):
        if self.libFile:
            try:
                with open(self.libFile, 'r') as FID:
                    tmpLib = json.load(FID, cls=LibraryCoders.LibraryDecoder)
                    if isinstance(tmpLib, MeasFilterLibrary):
                        #Update correlator filter lists to filter objects
                        for filt in tmpLib.filterDict.values():
                            if isinstance(filt, Correlator):
                                filterList = []
                                for f in filt.filters:
                                    filterList.append(tmpLib.filterDict[f])
                                filt.filters = filterList
                        self.filterDict.update(tmpLib.filterDict)
                        # grab library version
                        self.version = tmpLib.version
            except IOError:
                print("No measurement library found.")

    def json_encode(self):
        return {
            "filterDict": {label:filt for label,filt in self.filterDict.items()},
            "version": self.version
        }


measFilterList = [Channelizer, KernelIntegrator, Correlator, StateComparator,
                  AlazarStreamSelector, X6StreamSelector,
                  Plotter, WriteToHDF5]

if __name__ == "__main__":

    #Work around annoying problem with multiple class definitions
    from MeasFilters import Channelizer, Correlator, MeasFilterLibrary

    testFilter1 = Channelizer(label='M1')
    testFilter2 = Channelizer(label='M2')
    testFilter3 = Correlator(label='M3')
    testFilter4 = Correlator(label='M4')
    filterDict = {'M1':testFilter1, 'M2':testFilter2, 'M3':testFilter3,'M4':testFilter4}

    testLib = MeasFilterLibrary(libFile='MeasFilterLibrary.json', filterDict=filterDict)

    with enaml.imports():
        from MeasFiltersViews import MeasFilterManagerWindow

    app = QtApplication()
    view = MeasFilterManagerWindow(filterLib=testLib)
    view.show()

    app.start()
