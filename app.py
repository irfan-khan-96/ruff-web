from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField
from wtforms.validators import DataRequired
import uuid
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.secret_key = 'v_hBp8HYDrOzYDtvplmxlx6ctIrhEUwLzKnYuEFxBvs'  # Replace with a secure secret key

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Forms
class StashForm(FlaskForm):
    text = TextAreaField('Your Text', validators=[DataRequired()])
    submit = SubmitField('Save')

class EditStashForm(FlaskForm):
    text = TextAreaField('Edit Text', validators=[DataRequired()])
    submit = SubmitField('Update')

@app.route('/')
def index():
    saved_text = session.get('saved_text', '')
    return render_template('index.html', saved_text=saved_text)

@app.route('/stash', methods=['POST'])
def stash():
    form = StashForm()
    if form.validate_on_submit():
        text = form.text.data
        stashes = session.get('stashes', [])
        new_stash = {
            'id': str(uuid.uuid4()),
            'text': text
        }
        stashes.append(new_stash)
        session['stashes'] = stashes
        session['saved_text'] = ''  # Clear the saved text after stashing
        flash('Stash saved successfully!', 'success')
    else:
        flash('Failed to save stash. Please try again.', 'error')
    return redirect('/')

@app.route('/stashes')
def view_stashes():
    stashes = session.get('stashes', [])
    return render_template('stashes.html', stashes=stashes)

@app.route('/stashes/<stash_id>')
def view_stash(stash_id):
    stashes = session.get('stashes', [])
    stash = next((s for s in stashes if s['id'] == stash_id), None)
    if stash is None:
        flash('Stash not found.', 'error')
        return redirect(url_for('view_stashes'))
    return render_template('viewstash.html', stash=stash)

@app.route('/stashes/<stash_id>/edit', methods=['GET', 'POST'])
def edit_stash(stash_id):
    stashes = session.get('stashes', [])
    stash = next((s for s in stashes if s['id'] == stash_id), None)
    if stash is None:
        flash('Stash not found.', 'error')
        return redirect(url_for('view_stashes'))
    form = EditStashForm()
    if form.validate_on_submit():
        stash['text'] = form.text.data
        session['stashes'] = stashes
        flash('Stash updated successfully!', 'success')
        return redirect(url_for('view_stashes'))
    form.text.data = stash['text']
    return render_template('editstash.html', form=form, stash=stash)

@app.route('/stashes/<stash_id>/delete', methods=['POST'])
def delete_stash(stash_id):
    stashes = session.get('stashes', [])
    new_stashes = [s for s in stashes if s['id'] != stash_id]
    if len(new_stashes) == len(stashes):
        flash('Stash not found.', 'error')
    else:
        session['stashes'] = new_stashes
        flash('Stash deleted successfully!', 'success')
    return redirect(url_for('view_stashes'))

if __name__ == '__main__':
    app.run(debug=True)

