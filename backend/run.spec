# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('migrations', 'migrations')]
binaries = []
hiddenimports = ['flask_sqlalchemy', 'flask_migrate', 'logging.config', 'logging.handlers']
tmp_ret = collect_all('huggingface_hub')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('openpyxl')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('requests')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# Forecasting stack: StatsForecast (+ its compiled coreforecast/utilsforecast)
# and LightGBM (ships a lib_lightgbm binary). collect_all pulls their compiled
# artifacts and data files so the frozen backend can import them.
for _pkg in ('statsforecast', 'coreforecast', 'utilsforecast', 'lightgbm',
             'chronos', 'accelerate', 'einops'):
    tmp_ret = collect_all(_pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# pkg_resources (run unconditionally by PyInstaller's runtime hook) imports
# jaraco.text and platformdirs at import time; modern setuptools no longer
# vendors them. jaraco is a PEP 420 NAMESPACE package, so it must be collected
# as files ON DISK (collect_all) - putting it in hiddenimports lands it in the
# PYZ zip, where namespace resolution fails and the frozen app dies on boot
# with "No module named 'jaraco'".
for _pkg in ('jaraco.text', 'jaraco.context', 'jaraco.functools',
             'platformdirs', 'more_itertools'):
    tmp_ret = collect_all(_pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='run',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='.',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='run',
)
