
# DEPENDENCIES
import random
from moviepy import (
    CompositeVideoClip, 
    ImageClip, 
    ColorClip, 
    TextClip,
    VideoClip,
    AudioFileClip,
    concatenate_videoclips
)
from moviepy.decorators import requires_duration
import model_helper

# VIDEO CONSTANTS
VIDEO_TIME = 0
CLIP_TIME = 0

# ADDS PROGRESS BAR TO CLIP
@requires_duration
def add_progress_bar(
    clip: VideoClip, 
    color: tuple, 
    total_duration: float, 
    height: int = 20
):

    def filter(get_frame, t):
        global CLIP_TIME, VIDEO_TIME
        if t < CLIP_TIME:
            VIDEO_TIME += CLIP_TIME
        CLIP_TIME = t
        progression = (VIDEO_TIME + CLIP_TIME) / total_duration
        bar_width = int(progression * clip.w)
        frame = get_frame(t)
        frame[0:height, :bar_width] = color
        return frame
    
    return clip.transform(filter, apply_to="mask")

# CREATES FINAL VIDEO AND RENDERS
def render_video(
    clips: list, 
    filename: str, 
    speed_factor: float = 1,
    with_audio: bool = False,
    audio: AudioFileClip = None
) -> str:

    # Concatenate the clips
    final_clip = concatenate_videoclips(clips, method="compose")

    # Speed up video
    final_clip = final_clip.with_speed_scaled(factor=speed_factor)

    # Adds audio if prompted
    if with_audio:
        final_clip = final_clip.with_audio(audio)

    # Write the final video to a file
    final_clip.write_videofile(filename, fps=24)

    # Clean up clips
    for clip in clips:
        clip.close()
    
    return filename

# CREATES TEXT CLIP VIDEO
def create_text_clip(
    text: str, 
    duration: float,
    total_duration: float,
    photo: ImageClip = "",
    fontsize: int = 150, 
    text_stroke_width: int = 10,
    text_stroke_color: tuple = (0,0,0),
    text_color: tuple = (255,255,255), 
    has_photo: bool = False,
    bg_color: tuple = (0,0,0), 
    aspect_ratio: tuple[int, int] = (1080, 1920), 
    style: int = 1
) -> CompositeVideoClip:

    # Identifies font of clip
    match style:
        case 1:
            font = "fonts/fragile-bombers.otf"
        case 2:
            font = "fonts/fragile-bombers-attack.otf"
        case 3:
            font = "fonts/fragile-bombers-down.otf"
        case _:
            font = "fonts/fragile-bombers.otf"

    # Create a background color clip
    background_clip = ColorClip(
        size=aspect_ratio, 
        color=bg_color, 
        duration=duration
    )
    background_clip = add_progress_bar(
        clip=background_clip, 
        color=(255, 255, 255), 
        total_duration=total_duration
    )

    # Create a text clip
    text_clip = TextClip(
        text=text, 
        font_size=fontsize, 
        color=text_color,
        stroke_color=text_stroke_color,
        stroke_width=text_stroke_width,
        horizontal_align="center",
        vertical_align="center",
        size=(aspect_ratio[0], round(fontsize*1.5)),
        text_align="center",
        duration=duration
    ).with_position(("center", round(aspect_ratio[1]/2)-fontsize))
    shadow_text = TextClip(
        text=text, 
        font_size=fontsize, 
        color=(0,0,0),
        horizontal_align="center",
        vertical_align="center",
        size=(aspect_ratio[0], round(fontsize*1.5)),
        text_align="center",
        duration=duration
    ).with_position(("center", round(aspect_ratio[1]/2)-fontsize+10))

    # Composite the clips onto each other
    if has_photo:
        photo = photo.resized(width=aspect_ratio[0])
        photo = photo.with_duration(duration)
        photo = photo.with_position("center")
        return CompositeVideoClip([background_clip, photo, shadow_text, text_clip], size=aspect_ratio).with_fps(1)
    else:
        return CompositeVideoClip([background_clip, shadow_text, text_clip], size=aspect_ratio).with_fps(1)

# PROCESSES TEXT FOR SCRIPT
def process_script(
    text: str
):  
    
    # Finds special characters
    p_text = []
    non_filter_words = [" ", "'", "\""]
    for char in text:
        if char.isalnum():
            p_text.append(char)
        else:
            p_text.append(char)
            if char not in non_filter_words:
                p_text.append(" ")

    # Replaces special chars
    words = ("".join(p_text)).split(" ")
    p_words = []
    filter_words = ["", "\n", "."]
    for word in words:
        if word in filter_words:
            continue
        else:
            p_words.append(word)
            
    return p_words

# CREATES SCRIPT USING BETA
def create_script_beta(
    text: str
):
    
    # Generates total audio for video
    words = process_script(
        text=text
    )

    if len(words) > 0:

        # Generates tts and gets timestamps
        audio, audio_timestamps = model_helper.gen_tts_beta(
            words_array=words
        )
        if len(audio_timestamps) > 0:

            total_duration = sum(audio_timestamps)
            images = []
            image_urls = []

            # Gets photos for words
            for word in words:
                success, photo = model_helper.get_photo(query=word)
                if success:
                    images.append(photo[1])
                    image_urls.append(photo[0])
                else:
                    images.append("not found")

            return True, words, audio, audio_timestamps, images, total_duration
        else:
            model_helper.log("ERROR WITH AUDIO TIMESTAMPS.")
            return False, None, None, None, None, None
    else:
        model_helper.log("ERROR WITH SCRIPT PROCESSING.")
        return False, None, None, None, None, None
        
# CREATES VIDEO
def create_video_beta(
    text: str,
    speed_factor: float = 1
):
    
    # Create script and find times
    success, words, audio, audio_timestamps, images, total_duration = create_script_beta(
        text=text
    )

    if success:

        # Creates scenes
        scenes = []
        for word, audio_timestamp, image in zip(words, audio_timestamps, images):
            if image == "not found":
                scenes.append(
                    create_text_clip(
                        text=word,
                        fontsize=random.randint(75, 175),
                        duration=audio_timestamp,
                        has_photo=False,
                        photo=image,
                        total_duration=total_duration
                    )
                )
            else:
                scenes.append(
                    create_text_clip(
                        text=word,
                        fontsize=random.randint(75, 175),
                        duration=audio_timestamp,
                        has_photo=True,
                        photo=image,
                        total_duration=total_duration
                    )
                )

        # Renders final video
        return render_video(
            clips=scenes,
            filename="/tmp/output.mp4",
            speed_factor=speed_factor,
            with_audio=True,
            audio=audio
        )
    
    else:
        model_helper.log("VIDEO CREATION FAILED")