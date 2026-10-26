# VoiceType

> 설치·실행 검증 범위와 남은 확인 사항은 [공개 준비 상태](RELEASE_PLAN.md)에서 확인하세요.

Apple Silicon Mac용 로컬 한국어 음성 입력 도구. 녹음 중 스피커 음소거와 음악 재생 유지 모드를 선택할 수 있습니다.

VoiceType는 한국어 받아쓰기를 빠르게 입력하고, 회의나 음악을 재생 중인 상황에서도 스피커 소리가 마이크에 섞이는 것을 줄이기 위한 도구입니다. 음성을 Mac에서 전사하며, 받아쓰기 결과를 현재 커서 위치에 입력합니다.

버전별 주요 변경 사항은 [변경 이력](CHANGELOG.md)에서 확인할 수 있습니다.

## 빠른 시작

1. [저장소](https://github.com/code-flexer/voicetype)를 clone하거나 GitHub의 **Code → Download ZIP**으로 소스를 내려받아 압축을 해제합니다. 별도 설치용 ZIP은 필요하지 않습니다.
2. Apple Silicon Mac과 macOS 15 이상에서 Apple Command Line Tools를 준비합니다. 설치되어 있지 않다면 터미널에서 `xcode-select --install`을 실행하고 설치를 마칩니다.
3. 소스 폴더에서 `Install.command`를 더블 클릭하거나, 터미널에서 해당 폴더로 이동해 실행합니다.

   ```bash
   ./Install.command
   ```

4. 설치 화면의 안내를 따릅니다. 인터넷 연결이 필요하며, 설치 확인과 관리자 암호 입력을 요청할 수 있습니다.
5. 설치 후 macOS 권한을 허용하고, 글을 입력할 곳에 커서를 놓은 뒤 `⌘⌥D`로 녹음을 시작합니다. 다시 누르면 전사한 글이 입력됩니다.

터미널에서 소스를 받으려면 다음을 실행합니다.

```bash
git clone https://github.com/code-flexer/voicetype.git
cd voicetype
./Install.command
```

## 사전 준비물

- **Apple Silicon Mac과 macOS 15 이상**: Intel Mac과 Windows는 지원하지 않습니다.
- **Apple Command Line Tools**: 소스에서 Swift 오디오 보조 앱을 빌드하는 데 필요합니다. `xcode-select --install`로 설치합니다.
- **인터넷 연결과 저장 공간**: 첫 설치에서 프로그램, Python(실행 환경), Whisper(음성 인식 모델)를 내려받습니다.
- **설치 권한**: Homebrew(프로그램 설치 도구)를 처음 설치할 때 관리자 암호와 설치 확인을 요청할 수 있습니다.
- **macOS 권한 허용**: 마이크와 자동 입력을 위한 손쉬운 사용 권한이 필요합니다. 음악 재생 유지 모드는 시스템 오디오 권한도 필요합니다.

`uv`(Python 실행 환경과 패키지 관리 도구), `sox`(마이크 녹음 도구), `speexdsp`(스피커 소리 제거용 라이브러리), Hammerspoon(단축키와 자동 입력을 담당하는 앱)은 미리 설치하지 않아도 됩니다.

## 설치 시 수행하는 작업

`Install.command`가 빠진 Homebrew와 필요한 프로그램을 설치한 뒤 VoiceType 설치를 진행합니다. 이미 있는 프로그램은 건너뜁니다.

설치기는 Python 3.13, 프로젝트 의존성, `mlx-community/whisper-large-v3-turbo`(사용하는 Whisper 모델)를 준비하고 오디오 보조 앱을 Mac에서 빌드합니다. VoiceType를 로그인 시 자동 시작하도록 설정하며, Hammerspoon의 기존 설정은 백업하고 VoiceType 연동을 추가합니다.

설치가 끝나면 macOS 메뉴 막대에 **VoiceType**가 표시됩니다. 이후 음성 인식은 Mac에서 로컬로 수행합니다. 설치된 프로그램은 소스 폴더와 별도로 유지되므로, 설치 후 소스 폴더를 옮기거나 지워도 됩니다. 업데이트나 제거에 사용할 소스는 다시 내려받을 수 있습니다.

## 사용법

| 동작 | 방법 |
| --- | --- |
| 녹음 시작 및 종료 | `⌘⌥D` (`Command` + `Option` + `D`) |
| 스피커 동작 선택 | `⌘⌥⇧M` (`Command` + `Option` + `Shift` + `M`) |
| 받아쓰기 결과 입력 | 녹음을 끝내면 현재 커서 위치에 삽입 |

스피커 동작은 두 가지입니다.

- **Mute during recording(녹음 중 음소거)**: 녹음하는 동안 스피커를 음소거하고, 종료 시 원래 상태로 되돌립니다. 기본 설정입니다.
- **Keep music playing(음악 재생 유지)**: 음악을 계속 재생하면서 스피커 소리가 마이크에 들어가는 것을 줄입니다. 마이크와 시스템 오디오 녹음 권한이 필요합니다.

자동 입력이 되지 않아도 결과가 복사된 경우에는 `⌘V`로 직접 붙여 넣을 수 있습니다.

## 권한

VoiceType를 처음 사용할 때 macOS에서 마이크 권한을 요청합니다. Hammerspoon이 텍스트를 자동 입력할 수 있도록 손쉬운 사용 권한도 허용해야 합니다. 이 권한은 설치기가 자동으로 허용할 수 없습니다.

메뉴 막대의 **VoiceType**에서 다음 항목을 사용할 수 있습니다.

- **Grant input permission…(자동 입력 권한 요청)**: Hammerspoon의 손쉬운 사용 권한을 요청합니다.
- **Grant audio permissions…(오디오 권한 요청)**: 음악 재생 유지 모드에 필요한 마이크와 시스템 오디오 권한을 요청합니다.

권한을 변경한 뒤에도 동작하지 않으면 Hammerspoon을 다시 실행합니다.

## 업데이트 및 제거

VoiceKey가 설치되어 있으면 VoiceType 설치기가 기존 설치를 자동으로 인식합니다. 기존 자동 실행을 종료하고 설정을 이전한 뒤, 이전 설치와 로그를 `~/Library/Application Support/local.voicetype/backups/`(설치 백업 폴더)에 보관합니다. 설치가 실패하면 기존 자동 실행과 Hammerspoon 설정을 복원합니다.

이전 오디오 보조 앱의 권한은 초기화합니다. 새 **VoiceType Audio**의 마이크·시스템 오디오 권한을 확인하고, macOS가 요청하면 다시 허용합니다. Hammerspoon의 손쉬운 사용 권한은 계속 사용합니다. 권한을 초기화해도 macOS 설정의 이전 앱 항목은 남을 수 있습니다.

새 버전 소스의 `Install.command`를 실행하면 해당 버전을 설치하고 자동 실행 대상을 바꿉니다. 같은 버전은 중복 설치할 수 없으므로, 다시 설치하려면 기존 설치를 먼저 제거합니다. 업데이트나 제거 전에는 녹음을 마칩니다.

제거할 때는 소스 폴더의 `Uninstall.command`를 더블 클릭합니다. 제거기는 자동 시작과 Hammerspoon 연동을 해제합니다. 개인 설정, 백업, 공유 Whisper 모델은 보존하며, Homebrew와 함께 설치한 공용 프로그램도 제거하지 않습니다.

## 확인 범위

이 소스는 0.3.0 배포본에서 복원했습니다. 이전 배포본에서는 설치 관련 자동 검사, 배포 ZIP의 파일 무결성, 개발 Mac에서의 설정 이전과 새 서비스 시작을 확인한 기록이 있습니다. 현재 소스는 Python·셸 문법, 의존성 잠금, 소스 배포물·wheel 빌드, Swift 오디오 보조 앱 빌드 및 합성 데이터 자체 검사를 확인했습니다. 실제 설치·업데이트·제거·음성 입력과 필요한 프로그램이 전혀 없는 다른 Mac에서의 전체 설치는 아직 재검증하지 않았습니다.

## 라이선스

[MIT License](LICENSE). 의존 프로그램과 음성 인식 모델에는 각각의 라이선스가 적용됩니다. [외부 구성요소 안내](THIRD_PARTY.md)를 참고하세요.
