import os
import xml.etree.ElementTree as ET
import requests

def get_latest_post():
    try:
        tree = ET.parse('docs/feed.xml')
        root = tree.getroot()
        item = root.find('.//item')
        if item is not None:
            title = item.find('title').text
            link = item.find('link').text
            return title, link
    except Exception as e:
        print(f"Error reading RSS feed: {e}")
    return None, None

def post_to_discord(title, link, webhook_url):
    if not webhook_url:
        return
    payload = {
        "content": f"🚨 **New Autonomous Audit Published!** 🚨\n\n{title}\nRead the full report (and connect your agent to our MCP) here:\n{link}"
    }
    try:
        requests.post(webhook_url, json=payload)
        print("Successfully syndicated to Discord.")
    except Exception as e:
        print(f"Discord syndication failed: {e}")

def post_to_twitter(title, link, api_key, api_secret, access_token, access_token_secret):
    import tweepy
    if not all([api_key, api_secret, access_token, access_token_secret]):
        return

    try:
        # Authenticate using Twitter API v2
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret
        )
        
        tweet_text = f"🚨 New Autonomous Audit Published! 🚨\n\n{title}\n\nRead the full report (and connect your agent to our MCP) here:\n{link}\n\n#BaseNetwork #AI #SmartContracts"
        client.create_tweet(text=tweet_text)
        print("Successfully syndicated to Twitter.")
    except Exception as e:
        print(f"Twitter syndication failed: {e}")

def main():
    print("Running Social Syndicator...")
    title, link = get_latest_post()
    if not title or not link:
        print("No post found to syndicate.")
        return

    discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")
    tw_api_key = os.getenv("TWITTER_API_KEY")
    tw_api_secret = os.getenv("TWITTER_API_SECRET")
    tw_access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    tw_access_secret = os.getenv("TWITTER_ACCESS_SECRET")
    
    if discord_webhook:
        post_to_discord(title, link, discord_webhook)
    else:
        print("No DISCORD_WEBHOOK_URL found. Skipping Discord syndication.")
        
    if all([tw_api_key, tw_api_secret, tw_access_token, tw_access_secret]):
        post_to_twitter(title, link, tw_api_key, tw_api_secret, tw_access_token, tw_access_secret)
    else:
        print("Missing one or more Twitter keys. Skipping Twitter syndication.")

if __name__ == '__main__':
    main()
