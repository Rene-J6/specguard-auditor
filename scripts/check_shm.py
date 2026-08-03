import ctypes,sys
path=r"C:\Users\JUN KIAT\anaconda3\envs\FYP\Lib\site-packages\torch\lib\shm.dll"
try:
    ctypes.WinDLL(path)
    print('LOADED_OK')
except Exception as e:
    print('ERROR',repr(e))
    import traceback; traceback.print_exc()
    sys.exit(1)
