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
from typing import Any, List, Optional, Union

from google import genai
from google.genai import types

from camel.models.base_audio_model import BaseAudioModel


class GeminiAudioModels(BaseAudioModel):
    r"""Provides access to Google's Gemini audio processing capabilities.
    
    Supports both text-to-speech (TTS) generation and audio understanding
    (speech-to-text, transcription, analysis, question answering) using
    Gemini's native audio models.
    
    TTS Features:
    - Single and multi-speaker speech generation
    - 30 prebuilt voice options
    - Natural language control over style, accent, pace, and tone
    - Support for 80+ languages
    
    Audio Understanding Features:
    - Speech-to-text transcription
    - Translation capabilities
    - Audio question answering
    - Custom audio analysis
    - Timestamp-based audio referencing
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
    ) -> None:
        r"""Initialize an instance of GeminiAudioModels.
        
        Args:
            api_key (str, optional): Gemini API key. If not provided, it will
                be read from the GEMINI_API_KEY environment variable.
        """
        super().__init__(api_key, url=None)
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        if not self._api_key:
            raise ValueError(
                "Gemini API key must be provided either through the api_key "
                "parameter or GEMINI_API_KEY environment variable"
            )
        
        self._client = genai.Client(api_key=self._api_key)

    def text_to_speech(
        self,
        input: str,
        *,
        storage_path: Optional[str] = None,
        model: str = "gemini-2.5-flash-preview-tts",
        **kwargs: Any,
    ) -> Union[List[bytes], bytes]:
        r"""Convert text to speech using Gemini's TTS model.
        
        Args:
            input (str): The text to convert to speech. This is the main
                content that will be spoken. For multi-speaker conversations,
                format as "Speaker1: text\nSpeaker2: text" and provide
                speaker_configs in kwargs.
            storage_path (str, optional): File path to save the generated
                audio. Must end with .wav extension. For long text that gets
                split into chunks, all chunks will be merged into a single
                WAV file at this path. If not provided, audio is returned
                but not saved. Example: "/tmp/output.wav"
            model (str, optional): Gemini TTS model name. Use
                "gemini-2.5-flash-preview-tts" (faster, default) or
                "gemini-2.5-pro-preview-tts" (higher quality).
            **kwargs: Additional arguments:
                - voice_name (str): Name of the voice to use. Must be one of:
                  'Kore', 'Puck', 'Zephyr', 'Orus', 'Fenrir', 'Leda', 'Aoede',
                  'Callirrhoe', 'Enceladus', 'Iapetus', 'Umbriel', 'Algieba',
                  'Despina', 'Erinome', 'Algenib', 'Rasalgethi', 'Achernar',
                  'Alnilam', 'Schedar', 'Gacrux', 'Pulcherrima', 'Achird',
                  'Zubenelgenubi', 'Vindemiatrix', 'Sadachbia', 'Sadaltager',
                  'Sulafat', 'Laomedeia', 'Autonoe'. Default: 'Kore'
                - speaker_configs (list): For multi-speaker audio only.
                  List of dictionaries, each with:
                  - 'speaker' (str): Speaker name (must match name in input text)
                  - 'voice_name' (str): Voice to use for this speaker
                  Example: [
                      {'speaker': 'Alice', 'voice_name': 'Kore'},
                      {'speaker': 'Bob', 'voice_name': 'Puck'}
                  ]
                  
        Returns:
            Union[List[bytes], bytes]: Audio data in PCM format (24kHz, 16-bit
                mono). Returns bytes for short text (single chunk). Returns
                List[bytes] for long text split into multiple chunks (each item
                is one chunk's audio data).
            
        Raises:
            Exception: If TTS generation fails or file writing fails.
            
        Examples:
            Single speaker with default voice:
            >>> audio = model.text_to_speech(
            ...     input="Hello, world!",
            ...     storage_path="/tmp/hello.wav"
            ... )
            
            Single speaker with specific voice:
            >>> audio = model.text_to_speech(
            ...     input="Say cheerfully: Have a wonderful day!",
            ...     voice_name='Puck',
            ...     storage_path="/tmp/cheerful.wav"
            ... )
            
            Multi-speaker conversation:
            >>> audio = model.text_to_speech(
            ...     input="Alice: How are you today?\nBob: I'm doing great!",
            ...     speaker_configs=[
            ...         {'speaker': 'Alice', 'voice_name': 'Kore'},
            ...         {'speaker': 'Bob', 'voice_name': 'Puck'}
            ...     ],
            ...     storage_path="/tmp/conversation.wav"
            ... )
        """
        try:
            # Extract voice configuration from kwargs
            voice_name = kwargs.pop('voice_name', 'Kore')
            speaker_configs = kwargs.pop('speaker_configs', None)
            
            # Build speech config
            if speaker_configs:
                # Multi-speaker configuration
                speaker_voice_configs = []
                for config in speaker_configs:
                    speaker_voice_configs.append(
                        types.SpeakerVoiceConfig(
                            speaker=config['speaker'],
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=config.get('voice_name', 'Kore')
                                )
                            )
                        )
                    )
                
                speech_config = types.SpeechConfig(
                    multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                        speaker_voice_configs=speaker_voice_configs
                    )
                )
            else:
                # Single speaker configuration
                speech_config = types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name
                        )
                    )
                )
            
            # Gemini TTS has a 32k token context window
            # Approximate: 1 token ≈ 4 characters, so ~128k characters max
            # Use a conservative limit to account for formatting
            max_chunk_size = 100000  # characters
            
            if len(input) > max_chunk_size:
                # Split long text into chunks
                audio_chunks = []
                chunk_index = 0
                remaining_text = input
                
                while remaining_text:
                    if len(remaining_text) <= max_chunk_size:
                        chunk = remaining_text
                        remaining_text = ''
                    else:
                        # Find the nearest sentence end before the chunk limit
                        chunk_end = max_chunk_size
                        # Look for period, exclamation, or question mark
                        for delimiter in ['. ', '! ', '? ']:
                            pos = remaining_text.rfind(delimiter, 0, max_chunk_size)
                            if pos != -1:
                                chunk_end = pos + len(delimiter)
                                break
                        
                        chunk = remaining_text[:chunk_end]
                        remaining_text = remaining_text[chunk_end:].lstrip()
                    
                    # Generate audio for this chunk
                    response = self._client.models.generate_content(
                        model=model,
                        contents=chunk,
                        config=types.GenerateContentConfig(
                            response_modalities=["AUDIO"],
                            speech_config=speech_config,
                            **kwargs,
                        ),
                    )
                    
                    # Extract audio data
                    audio_data = response.candidates[0].content.parts[0].inline_data.data
                    audio_chunks.append(audio_data)
                    chunk_index += 1
                
                # Merge all audio chunks
                merged_audio = b''.join(audio_chunks)
                
                # Save merged audio to file if storage path provided
                if storage_path:
                    try:
                        # Ensure directory exists
                        self._ensure_directory_exists(storage_path)
                        
                        # Write merged PCM data to WAV file
                        import wave
                        with wave.open(storage_path, 'wb') as wf:
                            wf.setnchannels(1)  # Mono
                            wf.setsampwidth(2)  # 16-bit
                            wf.setframerate(24000)  # 24kHz
                            wf.writeframes(merged_audio)
                    except Exception as e:
                        raise Exception(
                            "Error during writing the merged file"
                        ) from e
                
                # Return list of individual chunks
                return audio_chunks
            
            else:
                # Generate audio for single chunk
                response = self._client.models.generate_content(
                    model=model,
                    contents=input,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=speech_config,
                        **kwargs,
                    ),
                )
                
                # Extract audio data
                audio_data = response.candidates[0].content.parts[0].inline_data.data
                
                # Save to file if storage path provided
                if storage_path:
                    try:
                        # Ensure directory exists
                        self._ensure_directory_exists(storage_path)
                        
                        # Write PCM data to WAV file
                        import wave
                        with wave.open(storage_path, 'wb') as wf:
                            wf.setnchannels(1)  # Mono
                            wf.setsampwidth(2)  # 16-bit
                            wf.setframerate(24000)  # 24kHz
                            wf.writeframes(audio_data)
                    except Exception as e:
                        raise Exception("Error during writing the file") from e
                
                return audio_data
            
        except Exception as e:
            raise Exception("Error during TTS API call") from e

    def _split_audio(
        self, audio_file_path: str, chunk_size_mb: int = 20
    ) -> list:
        r"""Split the audio file into smaller chunks.
        
        Gemini API supports files up to 20MB for audio inputs.
        
        Args:
            audio_file_path (str): Path to the input audio file.
            chunk_size_mb (int, optional): Size of each chunk in megabytes.
                Defaults to `20`.
                
        Returns:
            list: List of paths to the split audio files.
        """
        from pydub import AudioSegment

        audio = AudioSegment.from_file(audio_file_path)
        audio_format = os.path.splitext(audio_file_path)[1][1:].lower()

        # Calculate chunk size in bytes
        chunk_size_bytes = chunk_size_mb * 1024 * 1024

        # Number of chunks needed
        num_chunks = os.path.getsize(audio_file_path) // chunk_size_bytes + 1

        # Create a directory to store the chunks
        output_dir = os.path.splitext(audio_file_path)[0] + "_chunks"
        os.makedirs(output_dir, exist_ok=True)

        # Get audio chunk len in milliseconds
        chunk_size_milliseconds = len(audio) // (num_chunks)

        # Split the audio into chunks
        split_files = []
        for i in range(num_chunks):
            start = i * chunk_size_milliseconds
            end = (i + 1) * chunk_size_milliseconds
            if i + 1 == num_chunks:
                chunk = audio[start:]
            else:
                chunk = audio[start:end]
            # Create new chunk path
            chunk_path = os.path.join(output_dir, f"chunk_{i}.{audio_format}")
            chunk.export(chunk_path, format=audio_format)
            split_files.append(chunk_path)
        return split_files

    def speech_to_text(
        self,
        audio_file_path: str,
        translate_into_english: bool = False,
        model: str = "gemini-3-flash-preview",
        **kwargs: Any,
    ) -> str:
        r"""Convert speech in an audio file to text (transcription).
        
        Automatically handles large audio files by splitting them into chunks
        if needed. Supports files up to 9.5 hours of audio content.
        
        Args:
            audio_file_path (str): Full path to the audio file to transcribe.
                Must be an existing file in one of the supported formats.
                Example: "/tmp/recording.mp3" or "/home/user/audio.wav".
                Supported audio file formats are: wav, mp3, aiff, aac, ogg, flac.
            translate_into_english (bool, optional): If True, transcribes
                AND translates the audio to English. If False, only
                transcribes in the original language. Defaults to False.
            model (str, optional): Gemini model to use for transcription.
                Use "gemini-3-flash-preview" (faster, default) or
                "gemini-3-pro-preview" (higher quality). Defaults to
                "gemini-3-flash-preview".
            **kwargs: Additional arguments passed to the Gemini API.
            
        Returns:
            str: The transcribed text. If translate_into_english=True,
                returns the English translation. For large files split into
                chunks, returns all chunks joined with spaces.
            
        Raises:
            ValueError: If audio file format is not supported. Supported
                formats are: wav, mp3, aiff, aac, ogg, flac.
            Exception: If transcription fails or file cannot be read.
            
        Examples:
            Basic transcription:
            >>> text = model.speech_to_text(
            ...     audio_file_path="/tmp/meeting.mp3"
            ... )
            
            Transcribe and translate to English:
            >>> english_text = model.speech_to_text(
            ...     audio_file_path="/tmp/spanish_speech.wav",
            ...     translate_into_english=True
            ... )
            
            Use higher quality model:
            >>> text = model.speech_to_text(
            ...     audio_file_path="/tmp/interview.mp3",
            ...     model="gemini-3-pro-preview"
            ... )
        """
        supported_formats = [
            "wav",
            "mp3",
            "aiff",
            "aac",
            "ogg",
            "flac",
        ]
        file_format = audio_file_path.split(".")[-1].lower()

        if file_format not in supported_formats:
            raise ValueError(f"Unsupported audio file format: {file_format}")
        
        try:
            # Check file size
            file_size_mb = os.path.getsize(audio_file_path) / (1024 * 1024)
            
            # For very large files (>100MB), split them into chunks
            if file_size_mb > 100:
                # Split audio into chunks
                audio_chunks = self._split_audio(audio_file_path, chunk_size_mb=95)
                texts = []
                
                for chunk_path in audio_chunks:
                    # Upload chunk (chunks should be <100MB after split)
                    myfile = self._client.files.upload(file=chunk_path)
                    
                    # Create the prompt
                    if translate_into_english:
                        prompt = (
                            "Please transcribe the following audio and translate "
                            "it into English. Provide only the transcribed and "
                            "translated text without any additional commentary."
                        )
                    else:
                        prompt = (
                            "Generate a transcript of the speech. Provide only "
                            "the transcribed text without any additional commentary."
                        )
                    
                    # Generate content with the uploaded file
                    response = self._client.models.generate_content(
                        model=model,
                        contents=[prompt, myfile],
                        config=types.GenerateContentConfig(
                            **kwargs,
                        ),
                    )
                    
                    texts.append(response.text)
                    
                    # Clean up chunk file
                    os.remove(chunk_path)
                
                # Clean up chunk directory
                chunk_dir = os.path.splitext(audio_file_path)[0] + "_chunks"
                if os.path.exists(chunk_dir):
                    os.rmdir(chunk_dir)
                
                return " ".join(texts)
            
            elif file_size_mb > 20:
                # Upload the audio file using Files API for files 20-100MB
                myfile = self._client.files.upload(file=audio_file_path)
                
                # Create the prompt based on whether translation is needed
                if translate_into_english:
                    prompt = (
                        "Please transcribe the following audio and translate "
                        "it into English. Provide only the transcribed and "
                        "translated text without any additional commentary."
                    )
                else:
                    prompt = (
                        "Generate a transcript of the speech. Provide only "
                        "the transcribed text without any additional commentary."
                    )
                
                # Generate content with the uploaded file
                response = self._client.models.generate_content(
                    model=model,
                    contents=[prompt, myfile],
                    config=types.GenerateContentConfig(
                        **kwargs,
                    ),
                )
                
                return response.text
            else:
                # Use inline data for smaller files (<20MB)
                with open(audio_file_path, 'rb') as f:
                    audio_bytes = f.read()
                
                # Determine MIME type
                mime_type_map = {
                    'wav': 'audio/wav',
                    'mp3': 'audio/mp3',
                    'aiff': 'audio/aiff',
                    'aac': 'audio/aac',
                    'ogg': 'audio/ogg',
                    'flac': 'audio/flac',
                }
                mime_type = mime_type_map.get(file_format, f'audio/{file_format}')
                
                # Create the prompt
                if translate_into_english:
                    prompt = (
                        "Please transcribe the following audio and translate "
                        "it into English. Provide only the transcribed and "
                        "translated text without any additional commentary."
                    )
                else:
                    prompt = (
                        "Generate a transcript of the speech. Provide only "
                        "the transcribed text without any additional commentary."
                    )
                
                # Generate content with inline audio
                response = self._client.models.generate_content(
                    model=model,
                    contents=[
                        prompt,
                        types.Part.from_bytes(
                            data=audio_bytes,
                            mime_type=mime_type,
                        )
                    ],
                    config=types.GenerateContentConfig(
                        **kwargs,
                    ),
                )
                
                return response.text

        except Exception as e:
            raise Exception("Error during STT API call") from e

    def audio_question_answering(
        self,
        audio_file_path: str,
        question: str,
        model: str = "gemini-3-flash-preview",
        **kwargs: Any,
    ) -> str:
        r"""Answer a question about audio content without transcribing it first.
        
        This method analyzes audio directly and answers questions about it,
        such as identifying speakers, detecting emotions, summarizing content,
        or answering specific questions about what was said.
        
        Args:
            audio_file_path (str): Full path to the audio file to analyze.
                Must be an existing file in a supported format.
                Example: "/tmp/podcast.mp3" or "/home/user/meeting.wav"
            question (str): The question to answer about the audio content.
                Be specific about what you want to know.
                Examples:
                - "What is the main topic discussed?"
                - "How many speakers are there?"
                - "What emotion does the speaker convey?"
                - "Summarize the key points from this audio"
                - "What question does the interviewer ask at 2:30?"
            model (str, optional): Gemini model to use. Use
                "gemini-3-flash-preview" (faster, default) or
                "gemini-3-pro-preview" (higher quality). Defaults to
                "gemini-3-flash-preview".
            **kwargs: Additional arguments passed to the Gemini API.
            
        Returns:
            str: The answer to the question based on the audio content.
            
        Raises:
            ValueError: If audio file format is not supported. Supported
                formats are: wav, mp3, aiff, aac, ogg, flac.
            Exception: If analysis fails or file cannot be read.
            
        Examples:
            Ask about content:
            >>> answer = model.audio_question_answering(
            ...     audio_file_path="/tmp/lecture.mp3",
            ...     question="What are the three main points covered?"
            ... )
            
            Identify speakers:
            >>> answer = model.audio_question_answering(
            ...     audio_file_path="/tmp/meeting.wav",
            ...     question="How many different speakers are in this audio?"
            ... )
            
            Detect emotion:
            >>> answer = model.audio_question_answering(
            ...     audio_file_path="/tmp/speech.mp3",
            ...     question="What is the speaker's emotional tone?"
            ... )
        """
        supported_formats = [
            "wav",
            "mp3",
            "aiff",
            "aac",
            "ogg",
            "flac",
        ]
        file_format = audio_file_path.split(".")[-1].lower()

        if file_format not in supported_formats:
            raise ValueError(f"Unsupported audio file format: {file_format}")
        
        try:
            # Check file size
            file_size_mb = os.path.getsize(audio_file_path) / (1024 * 1024)
            
            # Prepare the prompt
            prompt = (
                f"Answer the following question based on the given audio "
                f"information:\n\n{question}"
            )
            
            if file_size_mb > 20:
                # Upload the audio file for larger files
                myfile = self._client.files.upload(file=audio_file_path)
                
                # Generate content with the uploaded file
                response = self._client.models.generate_content(
                    model=model,
                    contents=[prompt, myfile],
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "You are a helpful assistant specializing in audio "
                            "analysis. Answer questions based on the audio content "
                            "provided."
                        ),
                        **kwargs,
                    ),
                )
            else:
                # Use inline data for smaller files
                with open(audio_file_path, 'rb') as f:
                    audio_bytes = f.read()
                
                # Determine MIME type
                mime_type_map = {
                    'wav': 'audio/wav',
                    'mp3': 'audio/mp3',
                    'aiff': 'audio/aiff',
                    'aac': 'audio/aac',
                    'ogg': 'audio/ogg',
                    'flac': 'audio/flac',
                }
                mime_type = mime_type_map.get(file_format, f'audio/{file_format}')
                
                # Generate content with inline audio
                response = self._client.models.generate_content(
                    model=model,
                    contents=[
                        prompt,
                        types.Part.from_bytes(
                            data=audio_bytes,
                            mime_type=mime_type,
                        )
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "You are a helpful assistant specializing in audio "
                            "analysis. Answer questions based on the audio content "
                            "provided."
                        ),
                        **kwargs,
                    ),
                )
            
            return response.text
            
        except Exception as e:
            raise Exception(
                "Error during audio question answering API call"
            ) from e

    def audio_analysis(
        self,
        audio_file_path: str,
        prompt: str,
        model: str = "gemini-3-flash-preview",
        **kwargs: Any,
    ) -> str:
        r"""Perform custom audio analysis with a specific prompt/instruction.
        
        This is a flexible method for any audio analysis task. You can provide
        custom instructions for transcription, translation, speaker diarization,
        emotion detection, summarization, or any combination of these.
        
        You can reference specific time segments using MM:SS format (e.g.,
        "Transcribe from 02:30 to 03:45").
        
        Args:
            audio_file_path (str): Full path to the audio file to analyze.
                Must be an existing file in a supported format.
                Example: "/tmp/audio.mp3" or "/home/user/recording.wav"
            prompt (str): Custom instruction for what to do with the audio.
                Be specific and detailed about the desired output.
                Can include timestamps in MM:SS format to reference specific
                segments.
                Examples:
                - "Transcribe this audio and identify all speakers"
                - "Summarize the main points discussed between 01:00 and 05:00"
                - "Detect the emotion at timestamp 02:30"
                - "Provide a transcript with speaker names and timestamps"
                - "Translate this audio to English and provide timestamps"
            model (str, optional): Gemini model to use. Use
                "gemini-3-flash-preview" (faster, default) or
                "gemini-3-pro-preview" (higher quality). Defaults to
                "gemini-3-flash-preview".
            **kwargs: Additional arguments passed to the Gemini API.
            
        Returns:
            str: The analysis result based on your prompt.
            
        Raises:
            ValueError: If audio file format is not supported. Supported
                formats are: wav, mp3, aiff, aac, ogg, flac.
            Exception: If analysis fails or file cannot be read.
            
        Examples:
            Custom transcription with speaker labels:
            >>> result = model.audio_analysis(
            ...     audio_file_path="/tmp/meeting.mp3",
            ...     prompt="Transcribe this meeting and label each speaker as Speaker A, B, or C"
            ... )
            
            Time-based analysis:
            >>> result = model.audio_analysis(
            ...     audio_file_path="/tmp/lecture.wav",
            ...     prompt="Summarize what is discussed from 10:00 to 15:30"
            ... )
            
            Emotion and speaker detection:
            >>> result = model.audio_analysis(
            ...     audio_file_path="/tmp/call.mp3",
            ...     prompt="Identify speakers and their emotional tone throughout"
            ... )
        """
        supported_formats = [
            "wav",
            "mp3",
            "aiff",
            "aac",
            "ogg",
            "flac",
        ]
        file_format = audio_file_path.split(".")[-1].lower()

        if file_format not in supported_formats:
            raise ValueError(f"Unsupported audio file format: {file_format}")
        
        try:
            # Check file size
            file_size_mb = os.path.getsize(audio_file_path) / (1024 * 1024)
            
            if file_size_mb > 20:
                # Upload the audio file for larger files
                myfile = self._client.files.upload(file=audio_file_path)
                
                # Generate content with the uploaded file
                response = self._client.models.generate_content(
                    model=model,
                    contents=[prompt, myfile],
                    config=types.GenerateContentConfig(
                        **kwargs,
                    ),
                )
            else:
                # Use inline data for smaller files
                with open(audio_file_path, 'rb') as f:
                    audio_bytes = f.read()
                
                # Determine MIME type
                mime_type_map = {
                    'wav': 'audio/wav',
                    'mp3': 'audio/mp3',
                    'aiff': 'audio/aiff',
                    'aac': 'audio/aac',
                    'ogg': 'audio/ogg',
                    'flac': 'audio/flac',
                }
                mime_type = mime_type_map.get(file_format, f'audio/{file_format}')
                
                # Generate content with inline audio
                response = self._client.models.generate_content(
                    model=model,
                    contents=[
                        prompt,
                        types.Part.from_bytes(
                            data=audio_bytes,
                            mime_type=mime_type,
                        )
                    ],
                    config=types.GenerateContentConfig(
                        **kwargs,
                    ),
                )
            
            return response.text
            
        except Exception as e:
            raise Exception("Error during audio analysis API call") from e
