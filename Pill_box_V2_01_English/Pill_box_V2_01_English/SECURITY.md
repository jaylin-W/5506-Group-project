# Security Notes

This project includes basic security features for a classroom/demo Flask application:

- CSRF protection with Flask-WTF
- Login rate limiting with Flask-Limiter
- Password hashing with Werkzeug
- Environment variables for sensitive settings
- Hidden editor route configurable through `.env`

For production deployment, use a strong `SECRET_KEY`, change `HOST_PASSWORD`, deploy behind HTTPS, and do not commit `.env` or database files.
