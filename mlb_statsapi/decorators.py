import functools


def try_and_log(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            # TODO Print stack trace and metadata
            pass

    return wrapper
