import sys
import logging
import dill
import types

class StateWrapper(dict):
    def __init__(self):
        super().__init__()
        self.data = None

    def setData(self, data):
        self.data = data

    def __getitem__(self, key):
        assert self.data
        return self.data.__getitem__(key)

    def __setitem__(self, key, value):
        assert self.data
        return self.data.__setitem__(key, value)

class Chunk(object):
    def __init__(self, chash, objHash, codeObject, sourceChunk, lineno,
                 end_lineno, prevChunk):

        self.chash = chash
        self.codeObject = codeObject
        self.objHash = objHash
        self.sourceChunk = sourceChunk
        self.lineRange = range(lineno, end_lineno + 1)
        self.prevChunk = prevChunk

        # all chunks -- of the same "execution chain" / ChunkManager -- share
        # the same stateWrapper. Only for the DummyInitialChunk
        # (-> prevChunk is None) a new StateWrapper is created -- and shared
        # with all other chunks
        self.stateWrapper = prevChunk.stateWrapper if prevChunk \
                                                   else StateWrapper()

        self.valid = False
        self.output = None

    def update(self, sourceChunk, lineno, end_lineno):
        self.sourceChunk = sourceChunk
        self.lineRange = range(lineno, end_lineno+1)

    def execute(self):
        logging.debug('exec %s', self.getDebugId())

        assert self.prevChunk
        assert self.prevChunk.valid

        # store the sys.modules before we execute this chunk
        beforeModules = set([m for m in sys.modules.keys()])

        # derive namespace from prevChunk, based on a dill copy
        self.namespace = dill.copy(self.prevChunk.namespace)

        # copy function by reference! Otherwise their __globals__
        # field gets invalid
        for k, v in self.prevChunk.namespace.items():
            if isinstance(v, types.FunctionType):
                self.namespace[k] = v

        # set our local namespace as "global namespace". This needs to be
        # wrapped, because all function objects contain a reference to the
        # global namespace (at chunk execution time! -> func.__globals__).
        # But since we want it to run on this chunks globals, we need a
        # wrapper to exchange the global namespace under the hood
        self.stateWrapper.setData(self.namespace)

        # and execute the chunk and capture stdout
        with dill.temp.capture() as stdoutBuffer:
            errorMsg = ''
            try:
                exec(self.codeObject, self.stateWrapper)
            except Exception:
                import traceback
                errorMsg = traceback.format_exc()
                self.valid = False
            else:
                self.valid = True

            self.output = errorMsg + stdoutBuffer.getvalue().strip()

        # unload modules that are not imported in the outside world
        # (outside of the exec envinronment) this is necessary to
        # make import xxxx work properly without reusing previously
        # imported instances and their state
        # buuut this does only work for modules that are not imported
        # in the outside world (outside the exec environment).....
        # I did not found a solution to save and restore the state of sys
        # for example... :(
        afterModules = set([m for m in sys.modules.keys()])
        for m in (afterModules - beforeModules):
            del sys.modules[m]

        return self.valid

    def getDebugId(self):
        return f'{self.lineRange.start}: {self.sourceChunk.splitlines()[0]}'

class DummyInitialChunk(Chunk):
    def __init__(self, initialNamespace):
        super().__init__(0, 0, None, None, 0, 0, None)
        self.namespace = initialNamespace
        self.valid = True

