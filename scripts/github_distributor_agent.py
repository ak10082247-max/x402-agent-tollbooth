import os
import requests
import asyncio
from typing import List, Dict
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.hooks import policy

def search_github_issues(query: str) -> str:
    """Queries the GitHub REST API for open bug reports. Returns JSON string."""
    url = f"https://api.github.com/search/issues?q={requests.utils.quote(query)}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return str(response.json().get("items", [])[:10])
    else:
        return f"Error searching issues: {response.text}"

def post_github_comment(issue_url: str, comment_body: str) -> str:
    """Authenticates and posts a reply to a GitHub issue. issue_url is the comments_url from the issue object."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return "Failed: GITHUB_TOKEN environment variable not set."
        
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}"
    }
    
    response = requests.post(issue_url, headers=headers, json={"body": comment_body})
    if response.status_code == 201:
        return "Comment posted successfully."
    else:
        return f"Failed to post comment: {response.text}"

async def my_approval_handler(tool_call):
    print("\n" + "="*50)
    print("ACTION PENDING: post_github_comment")
    args = tool_call.args
    print(f"Target URL: {args.get('issue_url')}")
    print(f"Drafted Comment:\n{args.get('comment_body')}")
    print("="*50)
    
    while True:
        ans = input("Approve this comment? (Y to approve, N to skip): ").strip().upper()
        if ans == 'Y':
            return True
        elif ans == 'N':
            return False

async def main():
    config = LocalAgentConfig(
        api_key=os.environ.get("GEMINI_API_KEY", "dummy"),
        tools=[search_github_issues, post_github_comment],
        policies=[
            policy.ask_user("post_github_comment", handler=my_approval_handler),
            policy.allow_all()
        ]
    )
    
    agent = Agent(config)
    
    prompt = """
    You are an automated support agent routing developers to fix database catalogs.
    
    Follow these steps exactly:
    1. Sequentially search GitHub issues for three specific queries using the search_github_issues tool:
       - "Next.js 16 turbopack" state:open
       - "Stripe webhook signature v2026" state:open
       - "Base RPC blob fee" state:open
       
    2. Analyze the issues found. Draft a helpful, contextual comment explaining the breaking change that they encountered.
    
    3. Include the relevant error page link in your comment so they can solve it. The links map to the queries:
       - Next.js: https://x402-agent-tollbooth.onrender.com/errors/nextjs-turbopack-action-error
       - Stripe: https://x402-agent-tollbooth.onrender.com/errors/stripe-webhook-signature-verification-failed
       - Base RPC: https://x402-agent-tollbooth.onrender.com/errors/base-evm-blob-fee-error
       
    4. Select the best 5 issues overall across the searches, and invoke the post_github_comment tool to submit your drafted replies to their comments_url.
    """
    
    print("Starting agentic loop...")
    async with agent:
        response = await agent.chat(prompt)
        print("\nAgent execution finished.")
        async for chunk in response:
            print(chunk, end="", flush=True)
        print()

if __name__ == "__main__":
    asyncio.run(main())
