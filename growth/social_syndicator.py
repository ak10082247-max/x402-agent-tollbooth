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

def post_to_twitter(title, link, bearer_token):
    # This is a stub. For actual Twitter API v2 posting, you need OAuth1.0a User Context (Consumer Key/Secret, Access Token/Secret).
    # If the user provides an automation webhook (like Make.com or Zapier) we can hit that instead.
    if not bearer_token:
        return
    print("Twitter API keys detected, but requires OAuth1.0a setup for automated tweeting.")
    # In a full implementation, we would use tweepy or direct OAuth1 requests here.

def main():
    print("Running Social Syndicator...")
    title, link = get_latest_post()
    if not title or not link:
        print("No post found to syndicate.")
        return

    discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")
    twitter_bearer = os.getenv("TWITTER_BEARER_TOKEN")
    
    if discord_webhook:
        post_to_discord(title, link, discord_webhook)
    else:
        print("No DISCORD_WEBHOOK_URL found. Skipping Discord syndication.")
        
    if twitter_bearer:
        post_to_twitter(title, link, twitter_bearer)
    else:
        print("No Twitter keys found. Skipping Twitter syndication.")

if __name__ == '__main__':
    main()
