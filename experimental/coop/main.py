# pip install flask flask_sqlalchemy flask_migrate flask_login
# pip install faiss-cpu  # For CPU version
# pip install faiss-gpu  # For GPU version

# remaining parts:
#
#  - users can respond to matches
#  - calculate embeddings for user profiles
#  - match finding in background:
#    - for users with <10 unanswered matches for their most recent profile,
#      by ASC(# of proposed matches):
#      - if embedding isn't yet computed, compute it
#      - go over other users with whom there isn't yet a proposed
#        match, closest embedding distance first
#      - create a match if they're compatible
#        - compatibility prompt: can include previous positive/negative
#          matches
#  - write tests
#  - write a frontend

#  - password update

#  - if user A already dismissed a match, we might not want to show it
#    to user B anymore (e.g.: maybe matches might have a limited TTL?)

from datetime import datetime

from flask import Flask, jsonify, request
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SECRET_KEY"] = "secret-key-goes-here"

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)


class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    # TODO: set maximum length
    profile = db.Column(db.Text)

    # TODO: add created_at


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    contact_info = db.Column(db.String(100))

    # TODO: store embedding

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # TODO: add created_at, updated_at


class ProfileMatchState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"))
    status = db.Column(db.String(10), default="pending")

    # user can comment on why they picked this outcome state -
    # e.g. "this sounds promising" / "i'm not interested in this" / ...
    comment = db.Column(db.String(1024))

    match_description = db.Column(db.String(1024))

    profile = db.relationship("Profile", backref="match_states")
    match = db.relationship("Match", backref="profile_match_states")

    # TODO: add created_at, updated_at


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    profile_match_state1_id = db.Column(
        db.Integer,
        db.ForeignKey("profile_match_state.id"),
    )
    profile_match_state2_id = db.Column(
        db.Integer,
        db.ForeignKey("profile_match_state.id"),
    )
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    profile_match_state1 = db.relationship(
        "ProfileMatchState",
        foreign_keys=[profile_match_state1_id],
    )
    profile_match_state2 = db.relationship(
        "ProfileMatchState",
        foreign_keys=[profile_match_state2_id],
    )


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route("/register", methods=["POST"])
def register():
    data = request.json
    user = User(
        username=data["username"],
        profile=data["profile"],
        contact_info=data["contact"],
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "User registered successfully."}), 201


# TODO:
#    dummy_hash = 'pbkdf2:sha256:150000$dummy$' + '0'*64  # A dummy hash to compare against
# this might be more defensive cause you won't ever match it since it's
# all-zeroes hash
DUMMY_HASH = generate_password_hash("")


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data["username"]).first()

    # TODO: secure random
    gold_hash = generate_password_hash("")

    if user is not None:
        user_exists = True
        gold_hash = user.password_hash
    else:
        user_exists = True
        gold_hash = DUMMY_HASH

    password_matches_gold_hash = check_password_hash(gold_hash, data["password"])

    if user_exists and password_matches_gold_hash:
        # If the user exists and the password is correct, log the user in
        login_user(user)
        return jsonify({"message": "Login successful"})
    else:
        # If the password is incorrect, return an error
        return jsonify({"message": "Invalid username or password"}), 401


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Logged out successfully"})


@app.route("/update_profile", methods=["POST"])
@login_required
def update_profile():
    data = request.json
    current_user.profile = data["profile"]

    # Delete all matches involving the current user
    user_match_states = UserMatchState.query.filter_by(user_id=current_user.id).all()

    # Delete all matches and corresponding user match states involving the current user
    Match.query.join(UserMatchState, (UserMatchState.match_id == Match.id)).filter(
        UserMatchState.user_id == current_user.id,
    ).delete(synchronize_session=False)
    UserMatchState.query.filter_by(user_id=current_user.id).delete(
        synchronize_session=False,
    )

    db.session.commit()
    return jsonify({"message": "Profile updated successfully"})


# @app.route('/find_matches', methods=['GET'])
# @login_required
# def find_matches():
#     # This is where you'd integrate your language model to find matches
#     # For now, we'll simulate with a simple search
#     potential_matches = User.query.filter(
#         User.id != current_user.id,
#         User.profile.contains(current_user.profile)).limit(
#             100).all()  # Limit to 100 results for example
#
#     matches = []
#     for match_user in potential_matches:
#         # Check if a match entry already exists to prevent duplicates
#         existing_match_state = UserMatchState.query.join(
#             UserMatchState.match
#         ).filter((UserMatchState.user_id == current_user.id) & (
#             (Match.user_match_state1.has(user_id=match_user.id))
#             | (Match.profile_match_state2.has(user_id=match_user.id)))).first()
#         if not existing_match_state:
#             profile_match_state1 = UserMatchState(user_id=current_user.id)
#             profile_match_state2 = UserMatchState(user_id=match_user.id)
#             db.session.add(profile_match_state1)
#             db.session.add(profile_match_state2)
#             new_match = Match(profile_match_state1=profile_match_state1,
#                               profile_match_state2=profile_match_state2)
#             db.session.add(new_match)
#             matches.append({
#                 'username': match_user.username,
#                 'profile': match_user.profile
#             })
#     db.session.commit()
#     return jsonify(matches)


@app.route("/respond_match", methods=["POST"])
@login_required
def respond_match():
    data = request.json
    profile_match_state = UserMatchState.query.get(data["profile_match_state_id"])
    if profile_match_state and profile_match_state.user_id == current_user.id:
        profile_match_state.status = data["response"]
        db.session.commit()
        return jsonify({"message": "Response recorded"})
    return jsonify({"message": "Invalid request"}), 400


@app.route("/respond_match", methods=["POST"])
@login_required
def respond_match():
    data = request.json
    match = Match.query.get(data["match_id"])
    if match.user1_id == current_user.id:
        match.status1 = data["response"]
    elif match.user2_id == current_user.id:
        match.status2 = data["response"]
    db.session.commit()
    return jsonify({"message": "Response recorded"})


@app.route("/matches", methods=["GET"])
@login_required
def matches():
    confirmed_matches = Match.query.filter(
        (
            (Match.user1_id == current_user.id)
            & (Match.status1 == "yes")
            & (Match.status2 == "yes")
        )
        | (
            (Match.user2_id == current_user.id)
            & (Match.status1 == "yes")
            & (Match.status2 == "yes")
        ),
    ).all()
    match_details = []
    for match in confirmed_matches:
        other_user_id = (
            match.user2_id if match.user1_id == current_user.id else match.user1_id
        )
        other_user = User.query.get(other_user_id)
        match_details.append(
            {"username": other_user.username, "contact_info": other_user.contact_info},
        )
    return jsonify(match_details)


if __name__ == "__main__":
    app.run(debug=True)
