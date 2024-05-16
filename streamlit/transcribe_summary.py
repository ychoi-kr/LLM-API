from pydoc import cli
import streamlit as st
from pytube import YouTube
from openai import BadRequestError, OpenAI
import os
import tempfile


# 클라이언트 초기화
openai_client = OpenAI(
    api_key=st.secrets["OPENAI_API_KEY"]
)
upstage_client = OpenAI(
    api_key=st.secrets["UPSTAGE_API_KEY"],
    base_url="https://api.upstage.ai/v1/solar"
)

def get_video_info(url):
    yt = YouTube(url)
    title = yt.title
    # pytube에서 description을 가져오지 못하는 경우, fallback으로 description을 가져옴
    description = yt.description if yt.description else get_description_fallback(url)
    print(f"\nTitle: {title}\nDescription: {description}")
    return title, description

# https://github.com/pytube/pytube/issues/1626#issuecomment-1775501965
def get_description_fallback(url):
    yt = YouTube(url)
    for n in range(6):
        try:
            description =  yt.initial_data["engagementPanels"][n]["engagementPanelSectionListRenderer"]["content"]["structuredDescriptionContentRenderer"]["items"][1]["expandableVideoDescriptionBodyRenderer"]["attributedDescriptionBodyText"]["content"]            
            return description
        except:
            continue
    return False

def download_audio(url):
    print("Downloading audio...")
    video = YouTube(url).streams.filter(only_audio=True).first().download()
    return video

def trim_file_to_size(filepath, max_size):
    file_size = os.path.getsize(filepath)
    print(f"File size: {file_size} bytes")

    if file_size <= max_size:
        return filepath

    print(f"File size exceeds the maximum size of {max_size} bytes. Trimming the file...")
    # 원본 파일의 확장자를 유지하기 위해 파일명에서 확장자 추출
    _, file_ext = os.path.splitext(filepath)

    # 파일 크기가 최대 크기를 초과하는 경우, 처리 로직
    with open(filepath, "rb") as file:
        data = file.read(max_size)

    # 임시 파일 생성 및 데이터 쓰기
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_ext)
    temp_file.write(data)
    temp_file.close()

    return temp_file.name

def transcribe(audio_filepath, language=None, response_format='text', prompt=None):
    # 파일 크기 제한 (25MB)
    # Maximum content size limit는 26214400이지만 여유를 두기 위해 26210000으로 설정
    MAX_FILE_SIZE = 26210000

    # 파일 크기를 확인하고 필요한 경우 자르기
    trimmed_audio_filepath = trim_file_to_size(audio_filepath, MAX_FILE_SIZE)

    # 받아쓰기
    print("Transcribing audio...")
    with open(trimmed_audio_filepath, "rb") as file:
        # 매개변수 딕셔너리 생성
        kwargs = {
            'file': file,
            'model': "whisper-1",
            'response_format': response_format
        }

        # language가 제공되면 딕셔너리에 추가
        if language is not None:
            kwargs['language'] = language

        # prompt가 제공되면 딕셔너리에 추가
        if prompt is not None:
            kwargs['prompt'] = prompt

        # 받아쓰기 요청
        transcript = openai_client.audio.transcriptions.create(**kwargs)

    # 결과 저장
    st.session_state.transcript = transcript

    # 임시 파일이 생성되었을 경우 삭제
    if trimmed_audio_filepath != audio_filepath:
        os.remove(trimmed_audio_filepath)

def summarize(transcript, client, model):
    print(f"Summarizing transcript using model: {model}")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system",
             "content": f"First, summarize the transcription briefly in the same language in which the original dialogue was spoken. And then, if it is not in Korean, write a Korean summary as well.\n\nFORMAT:\n<summary_in_original_language>\n\nKorean summary:\n<korean_summary>"},
            {"role": "user", "content": transcript},
        ],
    )
    print("Summary generated.")
    return response.choices[0].message.content

def extract_dialogues_from_srt(srt_content):
    lines = srt_content.strip().split('\n')
    # 2번째 인덱스부터 시작해서 매 4번째 줄마다 추출 (0-based index이므로 실제로는 각 블록의 세 번째 줄)
    dialogues = [lines[i] for i in range(2, len(lines), 4)]
    return '\n'.join(dialogues)


# Streamlit UI 구성
st.title("Video Subtitles and Summary Generator")

url = st.text_input("Enter Video URL:")

# 유튜브 영상 정보 가져오기 버튼
if st.button("Load Video Info"):
    if url:
        title, description = get_video_info(url)
        st.session_state.video_info = f"Title: {title}\nDescription: {description}"
    else:
        st.error("Please enter a valid YouTube URL.")

# 영상 정보를 프롬프트에 표시
prompt = st.text_area(
    "What's the video about? (Optional)",
    value=st.session_state.get('video_info', ''),
    help="Provide a brief description of the video or include specific terms like unique names and key topics to enhance accuracy. This can include spelling out hard-to-distinguish proper nouns."
)

# 사용자에게 영상의 언어를 선택적으로 입력받는 UI 추가
language = st.selectbox("Select Language of the Video (optional):", ['', 'Korean', 'English', 'Japanese', 'Chinese', 'Spanish', 'French', 'German'])

response_format = st.selectbox("Select Output Format:", ('text', 'srt', 'vtt'))
st.session_state['response_format'] = response_format

# 세션 상태 초기화
if 'transcript' not in st.session_state:
    st.session_state.transcript = ""
if 'summary' not in st.session_state:
    st.session_state.summary = ""

if st.button("Generate Subtitles"):
    if url:
        with st.spinner('Downloading and transcribing video... This may take a while.'):
            filename = download_audio(url)
            transcribe(filename, response_format=response_format, prompt=prompt)
            os.remove(filename)  # 다운로드한 파일 삭제
        st.success('Done! Subtitles have been generated.')
        print("Transcription completed.")
    else:
        st.error("Please enter a URL.")

# 자막이 있을 경우, 자막 필드를 항상 표시
if st.session_state.transcript:
    st.text_area("Subtitles:", value=st.session_state.transcript, height=300)

# "Summarize" 버튼 처리 로직
if st.button("Summarize"):
    if st.session_state.transcript:
        transcript_to_summarize = st.session_state.transcript
        # srt 형식인 경우, 요약 전에 대화 내용만 추출
        if st.session_state['response_format'] == 'srt':
            transcript_to_summarize = extract_dialogues_from_srt(transcript_to_summarize)

        try:
            # 요약문 생성
            st.session_state.summary = summarize(
                transcript_to_summarize,
                client=upstage_client,
                model="solar-1-mini-chat"
            )
        except BadRequestError as e:
            # BadRequestError 발생 시 다른 모델로 재시도
            print("BadRequestError occurred: ", e)
            st.session_state.summary = summarize(
                transcript_to_summarize,
                client=openai_client,
                model="gpt-4o"
            )

# 요약문이 있을 경우, 요약문 필드를 표시
if st.session_state.summary:
    st.text_area("Summary:", value=st.session_state.summary, height=150)
