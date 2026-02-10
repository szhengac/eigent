# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

import os
from typing import List
from urllib.parse import urlparse
from camel.models import BaseAudioModel, BaseModelBackend
from camel.toolkits.function_tool import FunctionTool
from camel.toolkits import AudioAnalysisToolkit as BaseAudioAnalysisToolkit
from camel.toolkits.audio_analysis_toolkit import download_file

from app.component.environment import env
from app.service.task import Agents
from app.utils.listen.toolkit_listen import auto_listen_toolkit, listen_toolkit
from app.utils.toolkit.abstract_toolkit import AbstractToolkit
import logging

logger = logging.getLogger("audio_analysis_toolkit")


@auto_listen_toolkit(BaseAudioAnalysisToolkit)
class AudioAnalysisToolkit(BaseAudioAnalysisToolkit, AbstractToolkit):
    agent_name: str = Agents.multi_modal_agent

    def __init__(
        self,
        api_task_id: str,
        cache_dir: str | None = None,
        transcribe_model: BaseAudioModel | None = None,
        audio_reasoning_model: BaseModelBackend | None = None,
        timeout: float | None = None,
    ):
        if cache_dir is None:
            # Server mode: derive from server-owned data dir, not request-mutated env vars
            cache_dir = env("EIGENT_DATA_DIR", os.path.expanduser("~/.eigent/server_data"))
            cache_dir = os.path.join(cache_dir, "tmp")
        super().__init__(cache_dir, transcribe_model, audio_reasoning_model, timeout)
        self.api_task_id = api_task_id

    @listen_toolkit(
        inputs=lambda _, audio_path: f"transcribe audio file: {audio_path}",
    )
    def audio2text(self, audio_path: str) -> str:
        r"""Transcribe audio to text.

        Args:
            audio_path (str): The path to the audio file or URL.

        Returns:
            str: The transcribed text.
        """
        parsed_url = urlparse(audio_path)
        is_url = all([parsed_url.scheme, parsed_url.netloc])
        local_audio_path = audio_path

        # If the audio is a URL, download it first
        if is_url:
            try:
                local_audio_path = download_file(audio_path, self.cache_dir)
            except Exception as e:
                logger.error(f"Failed to download audio file: {e}")
                return f"Failed to download audio file: {e!s}"
        return super().audio2text(local_audio_path)

    @listen_toolkit(
        inputs=lambda _, audio_path, prompt: f"analyze audio file: {audio_path} with prompt: {prompt}",
    )
    def analyze_audio(self, audio_path: str, prompt: str) -> str:
        r"""Perform custom audio analysis with a specific prompt.
        
        This method allows you to analyze audio with custom instructions such as
        speaker diarization, emotion detection, summarization, or timestamp-based
        analysis. You can reference specific time segments using MM:SS format.

        Args:
            audio_path (str): The path to the audio file or URL.
            prompt (str): Custom instruction for analyzing the audio. Examples:
                - "Transcribe this audio and identify all speakers"
                - "Summarize the main points discussed between 01:00 and 05:00"
                - "Detect the emotion at timestamp 02:30"
                - "Provide a transcript with speaker names and timestamps"

        Returns:
            str: The analysis result based on the prompt.
        """
        logger.debug(
            f"Calling analyze_audio for audio file `{audio_path}` "
            f"with prompt `{prompt}`."
        )

        parsed_url = urlparse(audio_path)
        is_url = all([parsed_url.scheme, parsed_url.netloc])
        local_audio_path = audio_path

        # If the audio is a URL, download it first
        if is_url:
            try:
                local_audio_path = download_file(audio_path, self.cache_dir)
            except Exception as e:
                logger.error(f"Failed to download audio file: {e}")
                return f"Failed to download audio file: {e!s}"

        # Check if the transcribe_model supports audio_analysis
        if hasattr(self.transcribe_model, 'audio_analysis'):
            try:
                logger.debug("Using audio_analysis method")
                response = self.transcribe_model.audio_analysis(
                    local_audio_path, prompt
                )
                return response
            except Exception as e:
                logger.error(f"Audio analysis failed: {e}")
                return f"Failed to analyze audio: {e!s}"
        else:
            logger.warning(
                "Audio analysis not supported by the transcription model. "
                "Falling back to question answering."
            )
            return self.ask_question_about_audio(local_audio_path, prompt)

    @listen_toolkit(
        inputs=lambda _, text, **kwargs: f"convert text to speech: {text[:100]}...",
    )
    def text2audio(
        self,
        text: str,
        storage_path: str | None = None,
        voice_name: str = "Kore",
        model: str = "gemini-2.5-flash-preview-tts",
    ) -> str:
        r"""Convert text to speech and save as audio file.
        
        This method generates audio from text. For multi-speaker conversations,
        format the text as "Speaker1: text\nSpeaker2: text" and provide speaker
        configurations separately.

        Args:
            text (str): The text to convert to speech. For multi-speaker,
                format as "Name: text\nName2: text".
            storage_path (str, optional): Path to save the audio file. Must end
                with .wav extension. If not provided, a temporary file will be
                created in the cache directory. Example: "/tmp/output.wav"
            voice_name (str, optional): Name of the voice to use. Default is "Kore".
                Available voices: Kore, Puck, Zephyr, Orus, Fenrir, Leda, Aoede,
                Callirrhoe, Enceladus, Iapetus, Umbriel, Algieba, Despina, Erinome,
                Algenib, Rasalgethi, Achernar, Alnilam, Schedar, Gacrux, Pulcherrima,
                Achird, Zubenelgenubi, Vindemiatrix, Sadachbia, Sadaltager, Sulafat,
                Laomedeia, Autonoe.
            model (str, optional): TTS model to use. Default is 
                "gemini-2.5-flash-preview-tts". Can also use
                "gemini-2.5-pro-preview-tts" for higher quality.

        Returns:
            str: Path to the generated audio file.
        """
        logger.debug(f"Calling text2audio for text: {text[:100]}...")

        # Generate storage path if not provided
        if storage_path is None:
            import uuid
            os.makedirs(self.cache_dir, exist_ok=True)
            storage_path = os.path.join(
                self.cache_dir, f"tts_{uuid.uuid4()}.wav"
            )

        # Ensure directory exists
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)

        try:
            # Check if the transcribe_model supports text_to_speech
            if hasattr(self.transcribe_model, 'text_to_speech'):
                logger.debug("Using text_to_speech method")
                self.transcribe_model.text_to_speech(
                    input=text,
                    storage_path=storage_path,
                    voice_name=voice_name,
                    model=model,
                )
                logger.info(f"Audio saved to {storage_path}")
                return storage_path
            else:
                error_msg = (
                    "Text-to-speech not supported by the transcription model."
                )
                logger.error(error_msg)
                return error_msg
        except Exception as e:
            logger.error(f"Text-to-speech conversion failed: {e}")
            return f"Failed to convert text to speech: {e!s}"

    @listen_toolkit(
        inputs=lambda _, text, speakers, **kwargs: (
            f"convert multi-speaker text to speech with {len(speakers)} speakers"
        ),
    )
    def text2audio_multispeaker(
        self,
        text: str,
        speakers: List[dict],
        storage_path: str | None = None,
        model: str = "gemini-2.5-flash-preview-tts",
    ) -> str:
        r"""Convert multi-speaker text to speech with different voices.
        
        This method generates audio from text with multiple speakers, each using
        a different voice. The text should be formatted with speaker names.

        Args:
            text (str): The conversation text formatted as:
                "Speaker1: Hello\nSpeaker2: Hi there\nSpeaker1: How are you?"
            speakers (List[dict]): List of speaker configurations. Each dict should
                have:
                - 'speaker' (str): Speaker name (must match names in text)
                - 'voice_name' (str): Voice to use for this speaker
                Example: [
                    {'speaker': 'Alice', 'voice_name': 'Kore'},
                    {'speaker': 'Bob', 'voice_name': 'Puck'}
                ]
            storage_path (str, optional): Path to save the audio file. Must end
                with .wav extension. If not provided, a temporary file will be
                created.
            model (str, optional): TTS model to use. Default is
                "gemini-2.5-flash-preview-tts".

        Returns:
            str: Path to the generated audio file.
        """
        logger.debug(
            f"Calling text2audio_multispeaker with {len(speakers)} speakers"
        )

        # Generate storage path if not provided
        if storage_path is None:
            import uuid
            os.makedirs(self.cache_dir, exist_ok=True)
            storage_path = os.path.join(
                self.cache_dir, f"tts_multispeaker_{uuid.uuid4()}.wav"
            )

        # Ensure directory exists
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)

        try:
            # Check if the transcribe_model supports text_to_speech
            if hasattr(self.transcribe_model, 'text_to_speech'):
                logger.debug("Using text_to_speech with multi-speaker config")
                self.transcribe_model.text_to_speech(
                    input=text,
                    storage_path=storage_path,
                    speaker_configs=speakers,
                    model=model,
                )
                logger.info(f"Multi-speaker audio saved to {storage_path}")
                return storage_path
            else:
                error_msg = (
                    "Text-to-speech not supported by the transcription model."
                )
                logger.error(error_msg)
                return error_msg
        except Exception as e:
            logger.error(f"Multi-speaker TTS conversion failed: {e}")
            return f"Failed to convert text to speech: {e!s}"

    def get_tools(self) -> List[FunctionTool]:
        r"""Returns a list of FunctionTool objects representing the functions
        in the toolkit.

        Returns:
            List[FunctionTool]: A list of FunctionTool objects representing the
                functions in the toolkit.
        """
        return [
            FunctionTool(self.ask_question_about_audio),
            FunctionTool(self.audio2text),
            FunctionTool(self.analyze_audio),
            FunctionTool(self.text2audio),
            FunctionTool(self.text2audio_multispeaker),
        ]
