#!/usr/bin/env python3
from bloomstream.app import BloomStreamApp, main
from bloomstream.ui_lock import install_ui_lock

install_ui_lock(BloomStreamApp)

if __name__ == '__main__':
    main()
