#!/usr/bin/env python3
from bloomstream.app import BloomStreamApp, main
from bloomstream.ui_lock import install_ui_lock
from bloomstream.audio_meter_ui import install_audio_meter

install_ui_lock(BloomStreamApp)
install_audio_meter(BloomStreamApp)

if __name__ == '__main__':
    main()
