
# DEPENDENCIES
from datetime import datetime
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import json
import model_helper

# YOUTUBE VIDEO INTERFACE
class YouTubeClient():

    # Vars neccessary for YouTube Data API V3
    def __init__(self):

        # API defaults
        self.api_name = "youtube"
        self.version = "v3"
        self.scopes = [
            'https://www.googleapis.com/auth/youtube',
            'https://www.googleapis.com/auth/youtube.channel-memberships.creator',
            'https://www.googleapis.com/auth/youtube.force-ssl',
            'https://www.googleapis.com/auth/youtube.readonly',
            'https://www.googleapis.com/auth/youtube.upload',
            'https://www.googleapis.com/auth/youtubepartner',
            'https://www.googleapis.com/auth/youtubepartner-channel-audit'
        ]
        self.service = None

    # Gets client secret from database
    def getClientSecret(self):
        return model_helper.get_database(
            collection="creds",
            document="client_config"
        )
    
    # Gets channel token info from database
    def getChannelToken(self, name: str):
        return model_helper.get_database(
            collection="creds",
            document=name
        )

    # Starts flow for channel token
    def createChannelToken(self, name: str):

        # Starts flow
        flow = InstalledAppFlow.from_client_config(
            client_config=self.getClientSecret(),
            scopes=self.scopes
        )

        # Saves creds to database
        creds = flow.run_local_server(port=0)
        model_helper.set_database(
            collection="creds",
            document=name,
            data=json.loads(creds.to_json())
        )

    # Function to interface with YouTube API
    def createService(self, channel_token_name: str):
        try:

            # API vars defined
            API_SERVICE_NAME = self.api_name
            API_VERSION = self.version
            SCOPES = self.scopes

            # Gets creds
            client_token = self.getChannelToken(name=channel_token_name)
            creds = Credentials.from_authorized_user_info(
                info=client_token,
                scopes=SCOPES
            )
            model_helper.set_database(
                collection="creds",
                document=channel_token_name,
                data=json.loads(creds.to_json())
            )

            # Builds service
            self.service = build(API_SERVICE_NAME, API_VERSION, credentials=creds, static_discovery=False)
            print(API_SERVICE_NAME, API_VERSION, 'service created successfully')
            return True
        
        except Exception as e:

            # Prints error logging
            print(e)
            print(f'Failed to create service instance for {API_SERVICE_NAME}')
            return False
    
    # Uploads video with private status to YouTube (Quota Cost: 1600 units)
    def uploadVideo(
        self, 
        video_file: str, 
        title: str, 
        description: str, 
        tags: list, 
        category_id: str,
        privacy_status: str
    ) -> tuple[bool, str]:
        try:

            # Defines video metadata
            video_metadata = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'categoryId': category_id, # https://techpostplus.com/youtube-video-categories-list-faqs-and-solutions/
                    'tags': tags
                },
                'status': {
                    'privacyStatus': privacy_status,
                    'publishedAt': datetime.now().isoformat() + '.000Z',
                    'selfDeclaredMadeForKids': False
                },
                'notifySubscribers': False
            }
            
            # Uploads video
            media_file = MediaFileUpload(video_file)
            response_video_upload = self.service.videos().insert(
                part='snippet,status',
                body=video_metadata,
                media_body=media_file
            ).execute()
            return True, response_video_upload.get("id")
        
        except Exception as error:
            
            # Print error logging
            print(f"YouTube video upload failed with this error: {error}")
            return False, ""
    
    # Sets thumbnail for video (Quota Cost: 50 units)
    def setThumbnail(
        self, 
        thumbnail: str
    ):   
        try:

            # Sets thumbnail
            self.service.thumbnails().set(
                videoId=self.status["uploaded"]["video_id"],
                media_body=MediaFileUpload(thumbnail)
            ).execute()
            return True
        
        except Exception as error:
            
            # Prints error log
            print(f"YouTube failed to set thumbnail for video with this error: {error}")
            return False
    
    # Adds to YouTube playlist (Quota Cost: 50 units)
    def addPlaylist(
        self, 
        playlist_id: str
    ):
        try:

            # Defines request body
            playlist_metadata = {
                "contentDetails": {
                    "videoId": self.status["uploaded"]["video_id"]
                },
                'snippet': {
                    'playlistId': playlist_id,
                    'resourceId': {
                        "kind": "youtube#video",
                        "videoId": self.status["uploaded"]["video_id"],
                    }
                }
            }

            # Adds to playlist
            self.service.playlistItems().insert(
                part='snippet, contentDetails',
                body=playlist_metadata
            ).execute()
            return True
        
        except Exception as error:
            
            # Prints error log
            print(f"YouTube failed to add video to playlist with this error: {error}")
            return False

    # Retrieves number of videos in a playlist (Quota Cost: 1 unit)
    def retrievePlaylist(
        self, 
        playlist_id: str
    ):
        
        # Retrieve playlist items
        results = self.service.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50  
        ).execute()
        return results["pageInfo"]["totalResults"]

def upload_video(
    filename: str,
    type: str, 
    title: str, 
    description: str, 
    tags: list, 
    category_id: int, 
    privacy_status: str
):
    
    # Generate video
    youtube_api = YouTubeClient()
    youtube_api.createService(channel_token_name=type)
    success, id = youtube_api.uploadVideo(
        video_file=filename,
        title=title,
        description=description,
        tags=tags,
        category_id=category_id,
        privacy_status=privacy_status
    )

    if success:
        return True, id
    else:
        return False, "",

