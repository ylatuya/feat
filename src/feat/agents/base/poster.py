from zope.interface import implements

from feat.agents.base import message, replay, protocols
from feat.common import defer, reflect, serialization, fiber

from feat.interface.poster import *
from feat.interface.protocols import *


class MetaPoster(type(replay.Replayable)):

    implements(IPosterFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(MetaPoster, cls).__init__(name, bases, dct)


class BasePoster(protocols.BaseInitiator):

    __metaclass__ = MetaPoster

    implements(IAgentPoster)

    log_category = "poster"

    protocol_type = "Notification"
    protocol_id = None

    notification_timeout = 10

    ### Method to be Overridden ###

    def pack_payload(self, *args, **kwargs):
        return dict(args=args, kwars=kwargs)

    ### IAgentPoster Methods ###

    def notify(self, *args, **kwargs):
        d = defer.maybeDeferred(self.pack_payload, *args, **kwargs)
        d.addCallback(self._build_message)
        return d

    ### Private Methods ###

    @replay.immutable
    def _build_message(self, state, payload):
        msg = message.Notification()
        msg.payload = payload
        return state.medium.post(msg)
