from pathlib import Path
from opencover.config import Settings
from opencover.core.hardware_detector import HardwareInfo
from opencover.paths import AppPaths
from opencover.storage.database import Database
from opencover.ui.main_window import MainWindow, LyricPage


def test_private_full_package_enables_lyric_input(qtbot, tmp_path: Path):
    paths = AppPaths(tmp_path, *(tmp_path / name for name in ('workspace','weights','assets','config','external_backends','ffmpeg')))
    paths.ensure()
    (tmp_path/'PRIVATE_EDITION').write_text('测试版0.2',encoding='utf-8')
    (tmp_path/'LYRIC_EDITION').write_text('GAME + DiffSinger',encoding='utf-8')
    window = MainWindow(paths, Settings(minimize_to_tray=False),
                        HardwareInfo('Windows','CPU',16,'Test GPU',8,'1','13.0',None,'标准'),
                        Database(paths.workspace/'db.sqlite'))
    qtbot.addWidget(window)
    page=window.pages['改词翻唱 Beta']
    assert isinstance(page,LyricPage)
    assert page.generator_label.text()=='GAME + DiffSinger'
    assert not window.private_edition
