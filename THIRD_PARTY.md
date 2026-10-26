# 외부 구성요소

VoiceType 소스에는 [MIT 라이선스](LICENSE)가 적용됩니다. 아래 구성요소는 설치 과정에서 별도로 내려받으며, 각 프로젝트의 라이선스가 적용됩니다. 이 저장소에는 해당 패키지·실행 파일·모델 가중치를 포함하지 않습니다.

| 구성요소 | 용도 | 라이선스 및 원본 |
| --- | --- | --- |
| mlx-whisper 0.4.3 | 로컬 음성 인식 | [MIT, PyPI 메타데이터](https://pypi.org/pypi/mlx-whisper/0.4.3/json) |
| NumPy 2.5.4 | 오디오 수치 처리 | [BSD-3-Clause 및 포함 구성요소별 라이선스, PyPI 메타데이터](https://pypi.org/pypi/numpy/2.5.4/json) |
| webrtcvad-wheels 2.0.14.post1 | 음성 구간 감지 | [MIT 및 포함 WebRTC 고지](https://github.com/daanzu/py-webrtcvad-wheels/blob/master/LICENSE) |
| Lupa | 개발용 Lua 실행 | [MIT 계열, 프로젝트 라이선스](https://github.com/scoder/lupa/blob/master/LICENSE.txt) |
| Homebrew | 프로그램 설치 | [BSD-2-Clause](https://github.com/Homebrew/brew/blob/master/LICENSE.txt) |
| uv | Python 환경·패키지 설치 | [MIT 또는 Apache-2.0](https://github.com/astral-sh/uv#license) |
| SoX | 마이크 녹음 | [GPL-2.0-or-later 및 LGPL-2.1-or-later, Homebrew 정의](https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/s/sox.rb) |
| SpeexDSP | 스피커 소리 제거 | [BSD 계열, 프로젝트 고지](https://github.com/xiph/speexdsp/blob/master/COPYING) |
| Hammerspoon | 단축키·자동 입력 | [MIT](https://github.com/Hammerspoon/hammerspoon/blob/master/LICENSE) |
| Whisper large-v3-turbo | 음성 인식 모델 | [원본 모델 카드의 MIT 표기](https://huggingface.co/openai/whisper-large-v3-turbo) 및 [Whisper 라이선스](https://github.com/openai/whisper/blob/main/LICENSE) |

설치에 사용하는 모델은 [mlx-community/whisper-large-v3-turbo](https://huggingface.co/mlx-community/whisper-large-v3-turbo) 변환본입니다. 확인 시점의 변환본 모델 카드에는 별도 라이선스 표기가 없으며, 위 원본 모델의 라이선스를 참고할 수 있습니다. 이 저장소는 모델 가중치를 재배포하지 않습니다.

Python 전이 의존성은 `uv.lock`에 기록되어 있습니다. 각 패키지에 포함된 라이선스·저작권 고지를 유지해야 합니다. 향후 의존 프로그램이나 모델을 포함한 배포물을 만들 경우, 포함 버전별 라이선스와 고지·소스 제공 요구사항을 다시 확인해야 합니다.
