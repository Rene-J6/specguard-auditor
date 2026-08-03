import traceback
try:
    import torch
    print('TORCH_OK')
except Exception:
    traceback.print_exc()
