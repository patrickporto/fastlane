from datetime import datetime, timedelta, timezone
from json import dumps, loads
from uuid import uuid4

from croniter import croniter
from preggy import expect

from fastlane.models.task import Task


def test_enqueue1(client):
    """Test enqueue a job works"""
    task_id = str(uuid4())

    data = {
        "image": "ubuntu",
        "command": "ls",
    }

    rv = client.post(
        f'/tasks/{task_id}', data=dumps(data), follow_redirects=True)

    expect(rv.status_code).to_equal(200)

    obj = loads(rv.data)
    job_id = obj['jobId']
    expect(job_id).not_to_be_null()
    expect(obj['queueJobId']).not_to_be_null()

    queue_job_id = obj["queueJobId"]
    hash_key = f'rq:job:{queue_job_id}'
    app = client.application

    res = app.redis.exists(hash_key)
    expect(res).to_be_true()

    res = app.redis.hget(hash_key, 'status')
    expect(res).to_equal('queued')

    res = app.redis.hexists(hash_key, 'created_at')
    expect(res).to_be_true()

    res = app.redis.hexists(hash_key, 'enqueued_at')
    expect(res).to_be_true()

    res = app.redis.hexists(hash_key, 'data')
    expect(res).to_be_true()

    res = app.redis.hget(hash_key, 'origin')
    expect(res).to_equal('jobs')

    res = app.redis.hget(hash_key, 'description')
    expect(res).to_equal(
        f"fastlane.worker.job.run_job('{obj['taskId']}', '{job_id}', 'ubuntu', 'ls')"
    )

    res = app.redis.hget(hash_key, 'timeout')
    expect(res).to_equal('-1')

    task = Task.get_by_task_id(obj['taskId'])
    expect(task).not_to_be_null()
    expect(task.jobs).not_to_be_empty()

    j = task.jobs[0]
    expect(str(j.id)).to_equal(job_id)

    q = 'rq:queue:jobs'
    res = app.redis.llen(q)
    expect(res).to_equal(1)

    res = app.redis.lpop(q)
    expect(res).to_equal(queue_job_id)

    with client.application.app_context():
        count = Task.objects.count()
        expect(count).to_equal(1)


def test_enqueue2(client):
    """Test enqueue a job with the same task does not create a new task"""

    task_id = str(uuid4())

    data = {
        "image": "ubuntu",
        "command": "ls",
    }

    options = dict(
        data=dumps(data),
        headers={'Content-Type': 'application/json'},
        follow_redirects=True)

    rv = client.post(f'/tasks/{task_id}', **options)
    expect(rv.status_code).to_equal(200)

    obj = loads(rv.data)
    job_id = obj['jobId']
    expect(job_id).not_to_be_null()
    expect(obj['queueJobId']).not_to_be_null()

    rv = client.post(f'/tasks/{task_id}', **options)
    expect(rv.status_code).to_equal(200)
    obj = loads(rv.data)
    job_id = obj['jobId']
    expect(job_id).not_to_be_null()
    expect(obj['queueJobId']).not_to_be_null()

    task = Task.get_by_task_id(obj['taskId'])
    expect(task).not_to_be_null()
    expect(task.jobs).not_to_be_empty()

    with client.application.app_context():
        count = Task.objects.count()
        expect(count).to_equal(1)


def test_enqueue3(client):
    """Test enqueue a job at a future specific time"""

    app = client.application
    app.redis.flushall()

    task_id = str(uuid4())

    time = int(datetime.now(tz=timezone.utc).timestamp())

    data = {
        "image": "ubuntu",
        "command": "ls",
        "startAt": time,
    }
    options = dict(
        data=dumps(data),
        headers={'Content-Type': 'application/json'},
        follow_redirects=True)

    rv = client.post(f'/tasks/{task_id}', **options)
    expect(rv.status_code).to_equal(200)
    obj = loads(rv.data)
    job_id = obj['jobId']
    expect(job_id).not_to_be_null()
    expect(obj['queueJobId']).to_be_null()

    # res = app.redis.keys()
    res = app.redis.zrange(b'rq:scheduler:scheduled_jobs', 0, -1)
    expect(res).to_length(1)

    res = app.redis.zscore('rq:scheduler:scheduled_jobs', res[0])
    expect(res).to_equal(time)


def test_enqueue4(client):
    """Test enqueue a job in an hour"""

    cases = (
        ("48h", timedelta(hours=48)),
        ("1h", timedelta(hours=1)),
        ("5m", timedelta(minutes=5)),
        ("30s", timedelta(seconds=30)),
    )

    for (start_in, delta) in cases:
        enqueue_in(client, start_in, delta)


def enqueue_in(client, start_in, delta):
    app = client.application
    app.redis.flushall()

    task_id = str(uuid4())

    data = {
        "image": "ubuntu",
        "command": "ls",
        "startIn": start_in,
    }
    options = dict(
        data=dumps(data),
        headers={'Content-Type': 'application/json'},
        follow_redirects=True)

    rv = client.post(f'/tasks/{task_id}', **options)
    expect(rv.status_code).to_equal(200)
    obj = loads(rv.data)
    job_id = obj['jobId']
    expect(job_id).not_to_be_null()
    expect(obj['queueJobId']).to_be_null()

    # res = app.redis.keys()
    res = app.redis.zrange(b'rq:scheduler:scheduled_jobs', 0, -1)
    expect(res).to_length(1)

    time = int((datetime.now(tz=timezone.utc) + delta).timestamp())
    res = app.redis.zscore('rq:scheduler:scheduled_jobs', res[0])
    expect(res).to_equal(time)


def test_enqueue5(client):
    """Test enqueue a job using cron"""

    app = client.application
    app.redis.flushall()

    task_id = str(uuid4())

    data = {
        "image": "ubuntu",
        "command": "ls",
        "cron": "*/10 * * * *",
    }
    options = dict(
        data=dumps(data),
        headers={'Content-Type': 'application/json'},
        follow_redirects=True)

    rv = client.post(f'/tasks/{task_id}', **options)
    expect(rv.status_code).to_equal(200)
    obj = loads(rv.data)
    job_id = obj['jobId']
    expect(job_id).not_to_be_null()
    expect(obj['queueJobId']).to_be_null()

    res = app.redis.zrange(b'rq:scheduler:scheduled_jobs', 0, -1)
    expect(res).to_length(1)

    cron = croniter('*/10 * * * *', datetime.now())
    res = app.redis.zscore('rq:scheduler:scheduled_jobs', res[0])
    expected = cron.get_next(datetime)
    expect(res).to_equal(expected.timestamp())
