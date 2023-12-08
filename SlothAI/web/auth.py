from google.cloud import ndb

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask import current_app as app
from flask_login import login_user, login_manager, logout_user, login_required, current_user
import flask_login

from SlothAI.web.models import User, Transaction, Pipeline, Node, Template
from SlothAI.lib.util import random_string, email_user, sms_user, generate_token, random_number, random_string, slacker


from random import randrange
import datetime
import phonenumbers
from email_validator import validate_email, EmailNotValidError

# client connection
client = ndb.Client()

def get_brand(app):
    # brand setup
    brand = {}
    brand['name'] = app.config['BRAND']
    brand['favicon'] = app.config['BRAND_FAVICON']
    brand['color'] = app.config['BRAND_COLOR']
    brand['service'] = app.config['BRAND_SERVICE']
    brand['service_url'] = app.config['BRAND_SERVICE_URL']
    brand['github_url'] = app.config['BRAND_GITHUB_URL']
    brand['discord_url'] = app.config['BRAND_DISCORD_URL']
    brand['youtube_url'] = app.config['BRAND_YOUTUBE_URL']
    return brand

# logins
login_manager = flask_login.LoginManager()
login_manager.session_protection = "strong"

# blueprints for auth, money and code endpoints
auth = Blueprint('auth', __name__)


# logout
@auth.route('/logout')
def logout():
    logout_user()
    flash("You are logged out.")
    return redirect(url_for('site.home'))


@auth.route('/remove_all_caution')
@login_required
def remove():
    uid = current_user.uid

    try:
        Pipeline.delete_by_uid(uid)
        Node.delete_by_uid(uid)
        Template.delete_by_uid(uid)
        logout_user()
        User.remove_by_uid(uid)
        flash("Account data purged. You have been logged out because you have no account.")
        return redirect(url_for('auth.login'))
    except:
        flash("Something went wrong with that. Sorry.")
        return redirect(url_for('auth.login'))

@auth.route('/token_reset', methods=['POST'])
@login_required
def token_reset():
    data = request.get_json()
    uid = current_user.uid
    user = User.reset_token(uid)

    if user:
        if data.get('prompt') == "please":
            status = {'status': "You are welcome."};
        else:
            status = {'status': "Solve this puzzle."};
    else:
        status = {'status': "Please enter the token."};

    return jsonify(status), 200


# LOGIN GET
@auth.route('/login', methods=['GET'])
def login():
    try:
        if current_user.email:
            session = True
        else:
            session = False
    except Exception as ex:
        session = False

    next_url = request.args.get("next")

    if not next_url:
        next_url = request.form.get('next')

    # if we have no connection to the DB, this will handle it
    # secure transaction to POST
    transaction_id = random_string(13)
    _ = Transaction.create(uid="anonymous", tid=transaction_id)

    return render_template(
        'pages/login.html',
        config=app.config,
        session=session,
        app_id = random_string(9),
        transaction_id = transaction_id,
        next=next_url,
        brand=get_brand(app)
    )
    

# LOGIN POST
# requires transaction_id
@auth.route('/login', methods=['POST'])
def login_post():
    # bots
    password = request.form.get('password')
    if password:
        # there are no passwords, but there are hacker fucks
        return "( ︶︿︶)_╭∩╮ PASSWORD REQUIRED!\nALSO, GET OFF MY LAWN.", 500

    try:
        # check email and options
        valid = validate_email(request.form.get('email'))
        email = valid.email

        auth_ok = True

    except Exception as ex:
        print(ex)
        # reset the offer
        flash("Need to validate an email address.")
        return redirect(url_for('auth.email'))

    # handle bots filling out forms
    transaction_id = request.form.get('transaction_id')

    # only allow posts with transaction IDs (move to a decorator?)
    if transaction_id:
        with client.context():
            transaction = Transaction.query().filter(Transaction.tid==transaction_id).get()

            # if we find it, delete it and proceed
            if transaction:
                transaction.key.delete()
            else:
                return redirect(url_for('auth.login'))
    else:
        return redirect(url_for('auth.login'))


    # if we are asked to force a token login
    use_token = request.form.get('use_token')

    # opportunity handling (signup vs. login)
    op = request.args.get("op")
    if not op:
        op = request.form.get('op')
    
    if not op:
        op = "0"

    # check if user is already logged in
    try:
        # user logged in and doesn't want to upgrade
        if email == current_user.email and op == "0":
            # switch on dev for SSL
            if app.config['DEV'] == "True":
                return redirect(url_for('site.pipelines'))
            else:
                # production SSL
                return redirect(url_for('site.pipelines', _external=True, _scheme="https"))
    except:
        pass

    # at this point we're not logged in, but may have a destination in mind
    next_url = request.args.get('next')
    if not next_url:
        next_url = request.form.get('next')

    # options for next form
    options = {'email': email, 'op': op, 'next': next_url}

    # look the user up
    user = User.get_by_email(email)

    if not user:
        # no user, create user (this is the only place it should happen)
        user = User.create(email=email)
        subject = "Verify Email Address"

    elif use_token == "1":
        # change the subject and force skipping sms login below
        subject = "Backup Login Link"
    else:
        # subject
        subject = "Login Link"
            
        if user.phone != "+1" and user.phone:
            # generate code for use after auth.verify
            phone_code = random_number(6)

            with client.context():
                # rotate code
                # TODO: Add additional 2FA with Google Authenticator
                user.phone_code = phone_code
                user.updated = datetime.datetime.utcnow()
                user.put()

            # go ask for the last 4 digits of phone
            return redirect(url_for('auth.verify_phone', **options))

    # rotate the token
    with client.context():
        # only rotate if we have confirmed this user by email
        if user.mail_confirm:   
            mail_token = generate_token()
            user.mail_token = mail_token
            user.phone_code = generate_token() # secure phone code
            user.updated = datetime.datetime.utcnow()
            user.put()
        else:
            mail_token = user.mail_token

    # send user a login link (with next url even)
    if app.config['DEV'] == "True":
        login_link = "http://localhost:8080/token?mail_token=%s&op=%s" % (mail_token, op)
    else:
        login_link = "https://%s/token?mail_token=%s&op=%s" % (app.config['APP_DOMAIN'], mail_token, op)

    # handle next properly
    if next_url:
        login_link = login_link + "&next=%s" % next_url

    # allow non-confirmed user to request 5 emails
    if not user.mail_confirm and int(user.mail_tries) > 5:
        flash("Maximum retries for this email.")
        return redirect(url_for('auth.login'))
    else:
        with client.context():
            user.mail_tries = user.mail_tries + 1
            user.updated = datetime.datetime.utcnow()
            user.put()

    if app.config['DEV'] == "True":
        print("mail token is: %s" % user.mail_token)

    # a poem
    once_upon = [
        "Once upon a time there was a girl who lived in a old cabin were every time you took a step it would creak.",
        "'Squeak!',' the floor said.",
        "She lived alone and only knew the man that brought her food.",
        "He told her stories about her life like she was a magical princess who was destined to become Queen.",
        "But, she always said the same thing back to him, 'I am no royalty!', but he would always reply, 'Just you wait and see!'",
        "But one day at 12:00 when the food man was suppose to come there was a knock at the door.",
        "Raquel got up and went to the door and, like always, the cabin creaked and squeaked.",
        "She opened the door and there was a boy who had very fancy clothing and his hair was just so.",
        "'Can I help you, sir?', she asked."
    ]

    # randomize without duplication
    out_rand_1 = randrange(9)
    while True:
        out_rand_2 = randrange(9)
        if out_rand_2 != out_rand_1:
            break

    # email the user
    email_user(
        email,
        subject = subject, 
        html_content = """
        <html>
        <head>
        <style>
        button {
            padding: 10px 24px !important;
            outline: none !important;
            border: none !important;
            border-radius: 24px !important;
            background-color: #437ef6 !important;
            font-size:14px!important;
            color: #fff!important;
        }
        p {
            color: #222!important;
        }
        </style>
        </head>
        <body>
        <p>Hi 👋</p>

        <p>Thank you for using MittaAI!</p>

        <p>Here's your login token: <mark>%s</mark></p>

        <p>To login, please click the link below.</p>

        <p><button><a href="%s" target="_blank" style="color: #fff!important;">Access Your Account</a></button></p>

        <p>Cheers,</p>

        <p>Kord<br>
        🚀<br>
        https://mitta.ai<br>
        kordless@gmail.com<br>
        </p>

        <div>A portion of a story written by my beautiful daughter:</div>
        <div><span>%s</span></div>
        <div><span>%s</span></div>

        </body>
        </html>
        """ % (user.mail_token, login_link, once_upon[out_rand_1], once_upon[out_rand_2])
    )

    flash("Check your email for the login token.")
    return redirect(url_for('auth.token', **options))


# verify phone digits
@auth.route('/verify')
def verify_phone():
    email = request.args.get('email')
    if not email:
        email = request.form.get('email')
    next_url = request.args.get('next')
    if not next_url:
        next_url = request.form.get('next')
    op = request.args.get('op')
    if not op:
        op = request.form.get('op')

    # no email?
    if not email:
        return redirect(url_for('auth.email'))
    
    # find the user and set hint
    user = User.get_by_email(email)

    # options for next form
    options = {'email': email, 'op': op, 'next': next_url}

    if app.config['DEV'] == "True":
        print("phone hint includes: ", user.phone)

    return render_template('pages/verify.html', **options)


@auth.route('/verify', methods=['POST'])
def verify_phone_post():
    email = request.args.get('email')
    next_url = request.args.get('next')
    if not next_url:
        next_url = request.form.get('next')
    op = request.args.get('op')

    # options for next form, set op to 0 given we have a phone number
    options = {'email': email, 'op': 0, 'next': next_url}

    # get the digits
    digits = request.form.get('digits')

    # check the length
    if len(digits) > 4:
        flash("Verify the last 4 digits of your phone number!")
        return redirect(url_for('auth.email', **options))
    
    # find the user again and get their code
    user = User.get_by_email(email)
    code = user.phone[-4:]
    phone_code = user.phone_code

    # if the two match, we're in business to move on
    if code == digits:
        if app.config['DEV'] == "True":
            print("auth code is: %s" % phone_code)

        sms = sms_user(user.phone, message="%s is code for mitta.ai" % phone_code)
        
        if sms:
            return redirect(url_for('auth.tfa', **options))
        else:
            options['use_token'] = 1
            flash("Unable to send SMS token. You'll need to login with an email token.")
            return redirect(url_for('auth.email', **options))
    else:
        # silently reset the code, because validation was wrong
        with client.context():
            user.phone_code = generate_token() # secure phone code
            user.put()
        return redirect(url_for('auth.tfa', **options))


# tfa login
@auth.route('/tfa')
def tfa():
    # url paste login
    next_url = request.args.get('next')
    if not next_url:
        next_url = request.form.get('next')
    email = request.args.get('email')

    return render_template(
        'pages/tfa.html',
        config=app.config,
        next=next_url,
        email=email
    )


# mail token GET (from email)
@auth.route('/token')
def token():
    # check token and next_url
    mail_token = request.args.get('mail_token')
    next_url = request.args.get('next')
    if not next_url:
        next_url = request.form.get('next')
        if not next_url:
            next_url = None

    # options
    op = request.args.get("op")
    if not op:
        op = "0"
    options = {'op': op}

    # handle click from email or serve a form to take it
    if mail_token:
        # get the user
        user = User.get_by_mail_token(mail_token=mail_token)
        
        if user:
            # rotate token
            with client.context():
                user.mail_token = generate_token()
                user.mail_confirm = True
                user.authenticated = True
                user.mail_tries = 0
                user.failed_2fa_attempts = 0
                user.updated = datetime.datetime.utcnow()
                user.put()

            # log them in
            """
            """
            login_user(user)
            """
            """
            slacker(text="%s has logged in." % user.name)
        
            # user may choose to upgrade
            if op == "1":
                return redirect(url_for('auth.phone', **options))
            else:
                if next_url:
                    return redirect(next_url)
                else:
                    return redirect(url_for('site.pipelines'))

        else:
            flash("Incorrect token entered. Try again.")
            return redirect(url_for('auth.login', **options))
    else:
        return render_template('pages/token.html', config=app.config, op=op, next=next_url, brand=get_brand(app))


# verify code from emails
@auth.route('/token', methods=['POST'])
def token_post():
    # check token and email
    mail_token = request.form.get('mail_token')
    email = request.args.get('email')

    if not mail_token:
        return redirect(url_for('auth.email'))

    # url paste login
    next_url = request.args.get('next')
    if not next_url:
        next_url = request.form.get('next')

    # flow control
    op = request.form.get("op")
    if not op:
        op = request.args.get('op')
        if not op:
            op = "0"

    options = {'email': email, 'op': 0, 'next': next_url}

    # handle click from email or serve a form to take it
    if mail_token:
        # get the user BY TOKEN
        user = User.get_by_mail_token(mail_token=mail_token)
        try:
            if user.email == email:
                # rotate token, set logins
                with client.context():
                    user.mail_token = generate_token()
                    user.mail_confirm = True
                    user.authenticated = True
                    user.mail_tries = 0
                    user.updated = datetime.datetime.utcnow()
                    user.put()
            
        except Exception as ex:
            print(ex)
            # no user
            flash("Account credentials failed. Try again.")
            return redirect(url_for('auth.login', **options))

        # log them in
        """
        """
        login_user(user)
        """
        """
        slacker(text="%s has logged in." % user.name)
        
        # op
        if op == "1":
            return redirect(url_for('auth.phone', **options))
        else:
            if next_url:
                return redirect(next_url)
            else:
                return redirect(url_for('site.pipelines'))
    else:
        flash("Please enter a valid mail token!")
        return redirect(url_for('auth.login', **options)) 


# start sms verify signup
# does not require auth as /phone POST below does it
@auth.route('/phone')
def phone():
    email = request.args.get('email')
    if not email:
        # redirect with options for gathering phone
        options = {'op': 1, 'next': url_for('auth.phone')}
        return redirect(url_for('auth.email',**options))

    next_url = request.args.get('next')
    if not next_url:
        next_url = request.form.get('next')

    return render_template('pages/phone.html', next=next_url, email=email)


# paid signup using just a phone number for now
@auth.route('/phone', methods=['POST'])
@flask_login.login_required
def phone_post():
    try:
        # check phone number
        phone = phonenumbers.parse(request.form.get('phone'), "US")
    except:
        flash("Need to validate an actual phone number.")
        return redirect(url_for('auth.phone'))

    if not phonenumbers.is_possible_number(phone):
        flash("Need to validate a US phone number.")
        return redirect(url_for('auth.phone'))

    # see if we have a paid user with this phone number
    phone_e164 = phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)

    next_url = request.args.get('next')
    if not next_url:
        next_url = request.form.get('next')

    # remove the suggested next URL (that may have gotten us here via login)
    if next_url == url_for('auth.phone'):
        next_url = ""

    # flow control
    op = request.args.get("op")
    if not op:
        op = "0"

    options = {'op': op, 'next': next_url, 'phone': phone_e164}

    # rotate the current logged in user's code
    user = User.get_by_uid(current_user.uid)
    with client.context():
        user.phone_code = random_number(6)
        user.phone = phone_e164
        user.updated = datetime.datetime.utcnow()
        user.put()

    phone_code = user.phone_code

    sms_user(phone_e164, message="%s is code for mitta.ai" % phone_code)
    
    return redirect(url_for('auth.tfa', **options))


# handle the SMS challenge response
@auth.route('/tfa', methods=['POST'])
def tfa_post():
    # check phone number
    phone_code = request.form.get('phone_code')
    phone = request.args.get('phone')

    # flow control
    op = request.args.get("op")
    if not op:
        op = "0"
    options = {'op': op}
    
    next_url = request.args.get('next')
    if not next_url:
        next_url = request.form.get('next')

    # handle signuflow vs. upgrading user
    if request.args.get("email"):
        email = urllib.parse.unquote(request.args.get("email"))
        user = User.get_by_email(email)
        user_phone_code = user.phone_code
    else:
        try:
            user = User.get_by_uid(current_user.uid)
            user_phone_code = user.phone_code
        except:
            user = None
            user_phone_code = None

    # try from current user
    try:
        if user.phone != "+1" and user.phone:
            phone = user.phone
    except:
        # no user, no email, so return
        return redirect(url_for('auth.email'))

    # check if the code is correct
    # we update user below
    if user_phone_code == phone_code:
        # log them in
        """
        """
        login_user(user)
        """
        """
        slacker(text="%s has logged in." % user.name)

    else:
        # wrong code? we should reset the token and count failures
        # if this code never runs, there will be a 6 digit token in
        # the user's account which will never expire.
        with client.context():
            if user:
                user.phone_code = generate_token()
                user.failed_2fa_attempts = user.failed_2fa_attempts + 1
                user.updated = datetime.datetime.utcnow()
                user.put() 

        flash("Wrong code. Try again!")
        return redirect(url_for('auth.email', **options))

    # update user
    with client.context():
        user.phone = phone
        user.phone_code = generate_token()  # secure phone code
        user.paid = True
        user.authenticated = True
        user.updated = datetime.datetime.utcnow()
        user.put()

    if next_url:
        return redirect(next_url)
    else:
        if app.config['DEV'] == "True":
            return redirect(url_for('site.pipelines'))
        else:
            # production SSL
            return redirect(url_for('site.pipelines', _external=True, _scheme="https"))

# that's it
# <3 Dad