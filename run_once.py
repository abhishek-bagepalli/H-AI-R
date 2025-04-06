from flask import Flask, request, redirect
import google_auth_oauthlib.flow
import pickle
import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
app = Flask(__name__)

SCOPES = ['https://mail.google.com/']

@app.route('/')
def index():
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        'credentials.json', scopes=SCOPES)
    flow.redirect_uri = 'http://localhost:5000/oauth2callback'

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')

    return redirect(auth_url)

@app.route('/oauth2callback')
def oauth2callback():
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        'credentials.json', scopes=SCOPES)
    flow.redirect_uri = 'http://localhost:5000/oauth2callback'

    flow.fetch_token(authorization_response=request.url)

    creds = flow.credentials
    with open('token.json', 'wb') as token:
        pickle.dump(creds, token)

    return '✅ Authorization complete. You can close this window.'

if __name__ == '__main__':
    app.run(port=5000)
