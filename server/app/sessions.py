class Session:
    def __init__(self):
        self.history = []
        self.rollback_pending = False
        self.failed_request = ''

    def add_turn(self, user_text, assistant_text, files_changed):
        note = assistant_text
        if files_changed:
            if note and not note.endswith('.'):
                note = note + '.'
            note = note + ' Files changed: ' + ', '.join(files_changed) + '.'
        self.history.append({'role': 'user', 'content': user_text})
        self.history.append({'role': 'assistant', 'content': note})
        # Keep the last 10 turns (20 messages).
        while len(self.history) > 20:
            self.history.pop(0)

    def mark_committed(self):
        self.rollback_pending = False
        self.failed_request = ''

    def mark_rolled_back(self, user_text):
        self.rollback_pending = True
        self.failed_request = user_text

    def clear(self):
        self.history = []
        self.rollback_pending = False
        self.failed_request = ''
