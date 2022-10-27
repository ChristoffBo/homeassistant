Mimic TTS Server

Wait a minute after initial start as Mimic will download the first voice...

Web UI for testing can be found at "homeassistantIP":59125, please note after selecting a voice Mimic will download the voice first
so please be patiant.

Tested on Intel Nuc I7

 tts:

  - platform: marytts
    host: "homeassistantIP"
    port: 59125
    voice: en_US/ljspeech_low

Also Note If a new version of Technitium is launched, Backup Technitium in the Webui, uninstall the Addon and Reinstall.

License
MIT License

Copyright (c) 2019-2022 Christoff Bothma

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
