class Session:
    def __init__(self):
        self.history = []

    def add_turn(self, user_text, assistant_text, files_changed):
        note = assistant_text
        if files_changed:
            note = assistant_text
            if note and not note.endswith('.'):
                note = note + '.'
            note = note + ' Files changed: ' + ', '.join(files_changed) + '.'
        self.history.append({'role': 'user', 'content': user_text})
        self.history.append({'role': 'assistant', 'content': note})
        # Keep the last 10 turns (20 messages).
        while len(self.history) > 20:
            self.history.pop(0)

    def clear(self):
        self.history = []
