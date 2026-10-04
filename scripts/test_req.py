import urllib.request
import urllib.error
try:
  req = urllib.request.Request('https://x402-agent-tollbooth.onrender.com/sse', method='POST', data=b'{}')
  r = urllib.request.urlopen(req)
  print(r.status)
except urllib.error.HTTPError as e:
  print(e.code)
