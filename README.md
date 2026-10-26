# VoiceType

**Mac에서 말한 내용을 현재 커서 위치에 입력하는 로컬 한국어 받아쓰기 도구.**

Apple Silicon · macOS 15 이상 · MIT License

[시작하기](#시작하기) · [사용법](#사용법) · [변경 이력](CHANGELOG.md) · [문제 신고](https://github.com/code-flexer/voicetype/issues)

## 프로젝트 소개

VoiceType는 글을 입력할 곳에 커서를 두고 단축키로 녹음한 뒤, 전사한 한국어 텍스트를 삽입합니다. 초기 설치에서 모델을 내려받으며, 이후 음성 인식은 Mac에서 로컬로 수행합니다.

- **단축키로 받아쓰기**: `⌘⌥D`로 녹음을 시작하고, 다시 누르면 전사 결과를 입력합니다.
- **녹음 중 음소거**: 스피커를 잠시 음소거하고 녹음이 끝나면 원래 상태로 되돌립니다.
- **음악 재생 유지**: 음악을 계속 재생하면서 마이크에 섞인 스피커 소리를 줄이는 모드를 선택할 수 있습니다.
- **메뉴 막대에서 제어**: 녹음, 스피커 모드, 권한 요청을 VoiceType 메뉴에서 다룹니다.

### 주요 구성

Python과 MLX Whisper가 전사를, SoX가 기본 마이크 녹음을 담당합니다. 음악 재생 유지 모드는 Swift·ScreenCaptureKit으로 수집한 오디오와 SpeexDSP를 사용합니다. Hammerspoon은 단축키, 메뉴 막대, 자동 입력을 담당합니다. [외부 구성요소와 라이선스](THIRD_PARTY.md)를 참고하세요.

<details>
<summary>목차</summary>

- [시작하기](#시작하기)
- [사용법](#사용법)
- [업데이트 및 제거](#업데이트-및-제거)
- [검증 상태](#검증-상태)
- [기여](#기여)
- [라이선스](#라이선스)

</details>

## 시작하기

### 요구사항

| 항목 | 내용 |
| --- | --- |
| Mac | Apple Silicon, macOS 15 이상. Intel Mac과 Windows는 지원하지 않습니다. |
| 개발 도구 | 오디오 보조 앱을 빌드할 Apple Command Line Tools |
| 네트워크·저장 공간 | 첫 설치에서 프로그램, Python, 음성 인식 모델을 내려받는 데 필요 |
| 설치 권한 | Homebrew를 처음 설치할 때 설치 확인과 관리자 암호를 요청할 수 있음 |
| macOS 권한 | 마이크와 손쉬운 사용. 음악 재생 유지 모드는 시스템 오디오 권한도 필요 |

Apple Command Line Tools가 없다면 다음을 실행하고, 설치가 끝난 뒤 진행합니다.

```bash
xcode-select --install
```

### 설치

터미널에서 소스를 내려받아 설치합니다.

```bash
git clone https://github.com/code-flexer/voicetype.git
cd voicetype
./Install.command
```

Git을 사용하지 않으려면 [저장소](https://github.com/code-flexer/voicetype)의 **Code → Download ZIP**으로 소스를 받아 압축을 해제하고, 폴더 안의 `Install.command`를 더블 클릭합니다. 별도 설치용 ZIP은 필요하지 않습니다.

`uv`, `sox`, `speexdsp`, Hammerspoon은 미리 설치하지 않아도 됩니다. 설치 화면의 안내를 따르고, 완료 후 아래 [권한 설정](#권한-설정)을 확인하세요.

<details>
<summary>설치 시 다운로드와 설정 변경</summary>

설치기는 다음 작업을 수행합니다.

- 빠진 Homebrew와 필요한 프로그램을 설치합니다. 이미 있는 프로그램은 건너뜁니다.
- Python 3.13, 프로젝트 의존성, `mlx-community/whisper-large-v3-turbo` 모델을 준비합니다.
- Mac에서 오디오 보조 앱을 빌드합니다.
- VoiceType를 로그인 시 자동 시작하도록 설정합니다.
- 기존 Hammerspoon 설정을 백업하고 VoiceType 연동을 추가합니다.

설치가 끝나면 메뉴 막대에 **VoiceType**가 표시됩니다. 설치된 프로그램은 소스 폴더와 별도로 유지되므로, 소스 폴더를 옮기거나 지워도 됩니다. 업데이트나 제거에 사용할 소스는 다시 내려받을 수 있습니다.

</details>

## 사용법

1. 글을 입력할 앱에서 커서를 놓습니다.
2. `⌘⌥D`를 눌러 녹음을 시작하고 한국어로 말합니다.
3. 다시 `⌘⌥D`를 누르면 녹음이 끝나고, 전사한 글이 커서 위치에 입력됩니다.

자동 입력이 되지 않아도 결과가 복사된 경우에는 `⌘V`로 직접 붙여 넣을 수 있습니다.

| 단축키 | 동작 |
| --- | --- |
| `⌘⌥D` — Command + Option + D | 녹음 시작·종료 및 받아쓰기 결과 입력 |
| `⌘⌥⇧M` — Command + Option + Shift + M | 스피커 모드 선택 |

### 스피커 모드

메뉴 막대의 **VoiceType** 또는 `⌘⌥⇧M`에서 선택합니다.

| 모드 | 동작 |
| --- | --- |
| **Mute during recording** · 기본값 | 녹음 중 스피커를 음소거하고, 종료 시 원래 상태로 복원 |
| **Keep music playing** | 음악 재생을 유지하며 마이크에 섞인 스피커 소리를 줄임. 마이크·시스템 오디오 권한 필요 |

### 권한 설정

처음 사용할 때 macOS의 마이크 권한 요청을 허용합니다. 자동 입력에는 **Hammerspoon의 손쉬운 사용 권한**도 필요합니다. 설치기가 이 권한을 자동으로 허용할 수는 없습니다.

메뉴 막대의 **VoiceType**에서 권한을 요청할 수 있습니다.

- **Grant input permission…**: Hammerspoon의 손쉬운 사용 권한 요청
- **Grant audio permissions…**: 음악 재생 유지 모드에 필요한 마이크·시스템 오디오 권한 요청

권한을 변경한 뒤에도 동작하지 않으면 Hammerspoon을 다시 실행합니다.

## 업데이트 및 제거

**업데이트:** 새 버전 소스의 `Install.command`를 실행합니다. 해당 버전을 설치하고 자동 실행 대상을 바꿉니다. 같은 버전은 중복 설치할 수 없으므로, 다시 설치하려면 기존 설치를 먼저 제거합니다.

**제거:** 소스 폴더의 `Uninstall.command`를 더블 클릭합니다. 자동 시작과 Hammerspoon 연동을 해제하며, 개인 설정·백업·공유 Whisper 모델과 Homebrew로 설치한 공용 프로그램은 보존합니다.

업데이트나 제거 전에는 녹음을 마칩니다.

<details>
<summary>이전 VoiceKey 설치에서 이전하는 경우</summary>

설치기는 기존 VoiceKey 설치를 자동으로 인식합니다. 기존 자동 실행을 종료하고 설정을 이전한 뒤, 이전 설치와 로그를 `~/Library/Application Support/local.voicetype/backups/`에 보관합니다. 설치가 실패하면 기존 자동 실행과 Hammerspoon 설정을 복원합니다.

이전 오디오 보조 앱의 권한은 초기화합니다. 새 **VoiceType Audio**의 마이크·시스템 오디오 권한을 확인하고, macOS가 요청하면 다시 허용합니다. Hammerspoon의 손쉬운 사용 권한은 계속 사용합니다. 권한을 초기화해도 macOS 설정의 이전 앱 항목은 남을 수 있습니다.

</details>

## 검증 상태

현재 소스에서 확인한 범위는 다음과 같습니다.

- Python·셸 문법과 의존성 잠금 검사
- 소스 배포물·wheel 빌드와 라이선스 포함 여부
- Swift 오디오 보조 앱 빌드 및 합성 데이터 자체 검사

**실제 설치·업데이트·제거·음성 입력은 현재 소스에서 전체 재검증 전입니다.** 필요한 프로그램이 전혀 없는 다른 Mac에서의 전체 설치도 아직 검증하지 않았습니다.

이 소스는 0.3.0 배포본에서 복원했습니다. 이전 배포본에는 설치 자동 검사·ZIP 무결성, 개발 Mac에서의 설정 이전과 서비스 시작을 확인한 기록이 있습니다. 자세한 상태는 [공개 준비 상태](RELEASE_PLAN.md), 버전별 변경은 [변경 이력](CHANGELOG.md)을 참고하세요.

## 기여

버그나 개선 제안은 [Issues](https://github.com/code-flexer/voicetype/issues)에 남겨주세요. 버그 보고에는 Mac·macOS 환경과 재현 단계를 포함하면 도움이 됩니다. 코드 개선은 Pull Request로 제안할 수 있습니다.

## 라이선스

VoiceType 소스는 [MIT License](LICENSE)로 제공됩니다. 의존 프로그램과 음성 인식 모델에는 각각의 라이선스가 적용됩니다. [외부 구성요소 안내](THIRD_PARTY.md)를 참고하세요.
