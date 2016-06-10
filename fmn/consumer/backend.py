# FMN worker figuring out for a fedmsg message the list of recipient and
# contexts


import json
import logging
import time
import random

import pika
import fedmsg
import fedmsg.meta
import fedmsg_meta_fedora_infrastructure

import fmn.lib
import fmn.rules.utils
import backends as fmn_backends

import fmn.consumer.fmn_fasshim
from fedmsg_meta_fedora_infrastructure import fasshim

log = logging.getLogger("fmn")
log.setLevel('DEBUG')
CONFIG = fedmsg.config.load_config()
fedmsg.meta.make_processors(**CONFIG)

DB_URI = CONFIG.get('fmn.sqlalchemy.uri', None)
session = fmn.lib.models.init(DB_URI)

fmn.consumer.fmn_fasshim.make_fas_cache(**CONFIG)
# Duck patch fedmsg_meta modules
fasshim.nick2fas = fmn.consumer.fmn_fasshim.nick2fas
fasshim.email2fas = fmn.consumer.fmn_fasshim.email2fas
fedmsg_meta_fedora_infrastructure.supybot.nick2fas = \
    fmn.consumer.fmn_fasshim.nick2fas
fedmsg_meta_fedora_infrastructure.anitya.email2fas = \
    fmn.consumer.fmn_fasshim.email2fas
fedmsg_meta_fedora_infrastructure.bz.email2fas = \
    fmn.consumer.fmn_fasshim.email2fas
fedmsg_meta_fedora_infrastructure.mailman3.email2fas = \
    fmn.consumer.fmn_fasshim.email2fas
fedmsg_meta_fedora_infrastructure.pagure.email2fas = \
    fmn.consumer.fmn_fasshim.email2fas

CNT = 0

log.debug("Instantiating FMN backends")
backend_kwargs = dict(config=CONFIG)
backends = {
    'email': fmn_backends.EmailBackend(**backend_kwargs),
    'irc': fmn_backends.IRCBackend(**backend_kwargs),
    'android': fmn_backends.GCMBackend(**backend_kwargs),
    #'rss': fmn_backends.RSSBackend,
}

# But, disable any of those backends that don't appear explicitly in
# our config.
for key, value in backends.items():
    if key not in CONFIG['fmn.backends']:
        del backends[key]

# Also, check that we don't have something enabled that's not explicit
for key in CONFIG['fmn.backends']:
    if key not in backends:
        raise ValueError("%r in fmn.backends (%r) is invalid" % (
            key, CONFIG['fmn.backends']))

# If debug is enabled, use the debug backend everywhere
if CONFIG.get('fmn.backends.debug', False):
    for key in backends:
        log.debug('Setting %s to use the DebugBackend' % key)
        backends[key] = fmn_backends.DebugBackend(**backend_kwargs)


def get_preferences():
    print 'get_preferences'
    prefs = {}
    for p in session.query(fmn.lib.models.Preference).all():
        prefs['%s__%s' % (p.openid, p.context_name)] = p
    print 'prefs retrieved'
    return prefs


def update_preferences(openid):
    log.info("Loading and caching preferences for %r" % openid)
    for p in fmn.lib.models.Preference.by_user(session, openid):
        PREFS['%s__%s' % (p.openid, p.context_name)] = p


PREFS = get_preferences()


def callback(ch, method, properties, body):
    start = time.time()

    global CNT, PREFS
    CNT += 1

    start = time.time()

    data = json.loads(body)
    print data.keys()
    topic = data.get('topic', '')

    if '.fmn.' in topic:
        openid = data['body']['msg']['openid']
        PREFS = update_preferences(openid)
        if topic == 'consumer.fmn.prefs.update':  # msg from the consumer
            log.debug(
                "Done with refreshing prefs.  %0.2fs %s",
                time.time() - start, data['topic'])
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

    print data['raw_msg'].keys()
    recipients, context, raw_msg = \
        data['recipients'], data['context'], data['raw_msg']['body']

    log.debug("  Considering %r with %i recips" % (
        context, len(list(recipients))))

    backend = backends[context]
    for recipient in recipients:
        user = recipient['user']
        t = time.time()
        pref = PREFS.get('%s__%s' %(user, context))
        log.debug("pref retrieved in: %0.2fs", time.time() - t)

        if not pref.should_batch:
            log.debug(
                "    Calling backend %r with %r" % (backend, recipient))
            t = time.time()
            print backend
            backend.handle(session, recipient, raw_msg)
            log.debug("Handled by backend in: %0.2fs", time.time() - t)
        else:
            log.debug("    Queueing msg for digest")
            fmn.lib.models.QueuedMessage.enqueue(
                session, user, context, raw_msg)
        if ('filter_oneshot' in recipient
                and recipient['filter_oneshot']):
            log.debug("    Marking one-shot filter as fired")
            idx = recipient['filter_id']
            fltr = session.query(fmn.lib.models.Filter).get(idx)
            fltr.fired(session)
    session.commit()

    channel.basic_ack(delivery_tag=method.delivery_tag)
    log.debug("Done.  %0.2fs %s %s",
              time.time() - start, raw_msg['msg_id'], raw_msg['topic'])


connection = pika.BlockingConnection()

queue = 'refresh'
channel = connection.channel()
channel.exchange_declare(exchange=queue, type='fanout')
refresh_q = channel.queue_declare(exclusive=True)
refresh_q_name = refresh_q.method.queue
channel.queue_bind(exchange=queue, queue=refresh_q_name)

queue = 'backends'
channel.exchange_declare(exchange=queue, type='direct')
backends_q = channel.queue_declare(queue, durable=True)
channel.queue_bind(exchange=queue, queue=queue)

print 'started at %s backends' % backends_q.method.message_count
print 'started at %s refresh' % refresh_q.method.message_count

# Make sure we leave any other messages in the queue
channel.basic_qos(prefetch_count=1)
channel.basic_consume(callback, queue=queue)
channel.basic_consume(callback, queue=refresh_q_name)


try:
    print 'Starting consuming'
    channel.start_consuming()
except KeyboardInterrupt:
    pass
finally:
    channel.cancel()
    connection.close()
    session.close()
    print '%s tasks proceeded' % CNT
