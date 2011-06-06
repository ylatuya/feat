# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import types

from zope.interface import implements

from feat.common import log, decorator, serialization, fiber, manhole
from feat.interface import generic, agent, protocols
from feat.agents.base import (resource, recipient, replay, requester,
                              replier, partners, dependency, manager, )
from feat.agents.common import monitor

from feat.interface.agent import *
from feat.interface.agency import *


registry = dict()


@decorator.parametrized_class
def register(klass, name, configuration_id=None):
    global registry
    registry[name] = klass
    doc_id = configuration_id or name + "_conf"
    klass.descriptor_type = name
    klass.type_name = name + ":data"
    klass.configuration_doc_id = doc_id
    serialization.register(klass)
    return klass


def registry_lookup(name):
    global registry
    return registry.get(name, None)


@decorator.simple_function
def update_descriptor(function):

    @replay.immutable
    def decorated(self, state, *args, **kwargs):
        immfun = replay.immutable(function)
        method = types.MethodType(immfun, self, self.__class__)
        f = fiber.succeed(method)
        f.add_callback(state.medium.update_descriptor, *args, **kwargs)
        return f

    return decorated


@serialization.register
class BasePartner(partners.BasePartner):
    pass


@serialization.register
class MonitorPartner(monitor.PartnerMixin, BasePartner):

    type_name = "agent->monitor"


class Partners(partners.Partners):

    partners.has_many("monitors", "monitor_agent", MonitorPartner)


class MetaAgent(type(replay.Replayable), type(manhole.Manhole)):
    implements(agent.IAgentFactory)


class BaseAgent(log.Logger, log.LogProxy, replay.Replayable, manhole.Manhole,
                dependency.AgentDependencyMixin, monitor.AgentMixin):

    __metaclass__ = MetaAgent

    implements(agent.IAgent, generic.ITimeProvider)

    partners_class = Partners

    log_category = "agent"

    standalone = False

    categories = {'access': agent.Access.none,
                  'address': agent.Address.none,
                  'storage': agent.Storage.none}

    # resources required to run the agent
    resources = {'epu': 1}

    def __init__(self, medium):
        manhole.Manhole.__init__(self)
        log.Logger.__init__(self, medium)
        log.LogProxy.__init__(self, medium)
        replay.Replayable.__init__(self, medium)
        self.log_name = self.__class__.__name__

    @replay.immutable
    def restored(self, state):
        log.Logger.__init__(self, state.medium)
        log.LogProxy.__init__(self, state.medium)
        replay.Replayable.restored(self)

    def init_state(self, state, medium):
        state.medium = agent.IAgencyAgent(medium)
        state.resources = resource.Resources(self)
        state.partners = self.partners_class(self)

    @replay.immutable
    def get_status(self, state):
        return state.medium.state

    ### IAgent Methods ###

    @replay.immutable
    def initiate(self, state):
        state.medium.register_interest(replier.PartnershipProtocol)
        state.medium.register_interest(replier.ProposalReceiver)
        state.medium.register_interest(replier.Ping)

    @replay.immutable
    def startup(self, state):
        pass

    @replay.immutable
    def get_descriptor(self, state):
        return state.medium.get_descriptor()

    @replay.immutable
    def get_agent_id(self, state):
        desc = state.medium.get_descriptor()
        return desc.doc_id

    @replay.immutable
    def get_instance_id(self, state):
        desc = state.medium.get_descriptor()
        return desc.instance_id

    @replay.immutable
    def get_full_id(self, state):
        desc = state.medium.get_descriptor()
        return desc.doc_id + u"/" + unicode(desc.instance_id)

    @replay.journaled
    def shutdown(self, state):
        desc = self.get_descriptor()
        self.info('Agent shutdown, partners: %r', desc.partners)
        results = [x.on_shutdown(self) for x in desc.partners]
        fibers = [x for x in results if isinstance(x, fiber.Fiber)]
        f = fiber.FiberList(fibers)
        return f.succeed()

    def on_killed(self):
        self.info('Agents on_killed called.')

    def get_cmd_line(self, *args, **kwargs):
        raise NotImplemented('To be used for standalone agents!')

    ### ITimeProvider Methods ###

    @replay.immutable
    def get_time(self, state):
        return generic.ITimeProvider(state.medium).get_time()

    ### Public Methods ###

    @manhole.expose()
    @replay.journaled
    def wait_for_ready(self, state):
        return fiber.wrap_defer(state.medium.wait_for_state,
                                AgencyAgentState.ready)

    @replay.journaled
    def initiate_partners(self, state):
        desc = self.get_descriptor()
        results = [x.initiate(self) for x in desc.partners]
        fibers = [x for x in results if isinstance(x, fiber.Fiber)]
        f = fiber.FiberList(fibers)
        return f.succeed()

    @manhole.expose()
    def propose_to(self, recp, partner_role=None, our_role=None):
        return self.establish_partnership(recipient.IRecipient(recp),
                                          partner_role=partner_role,
                                          our_role=our_role)

    @replay.journaled
    def establish_partnership(self, state, recp, allocation_id=None,
                              partner_allocation_id=None,
                              partner_role=None, our_role=None,
                              substitute=None, allow_double=False):
        f = fiber.succeed()
        found = state.partners.find(recp)
        default_role = getattr(self.partners_class, 'default_role', None)
        our_role = our_role or default_role
        if not allow_double and found:
            msg = ('establish_partnership() called for %r which is already '
                   'our partner with the class %r.' % (recp, type(found), ))
            self.debug(msg)

            if substitute:
                f.add_callback(fiber.drop_param, state.partners.remove,
                               substitute)

            f.chain(fiber.fail(partners.DoublePartnership(msg)))
            return f
        f.add_callback(fiber.drop_param, self.initiate_protocol,
                       requester.Propose, recp, allocation_id,
                       partner_allocation_id,
                       our_role, partner_role, substitute)
        f.add_callback(requester.Propose.notify_finish)
        return f

    @replay.journaled
    def substitute_partner(self, state, partners_recp, recp, alloc_id):
        '''
        Establish the partnership to recp and, when it is successfull
        remove partner with recipient partners_recp.

        Use with caution: The partner which we are removing is not notified
        in any way, so he still keeps link in his description. The correct
        usage of this method requires calling it from two agents which are
        divorcing.
        '''
        partner = state.partners.find(recipient.IRecipient(partners_recp))
        if not partner:
            msg = 'subsitute_partner() did not find the partner %r' %\
                  partners_recp
            self.error(msg)
            return fiber.fail(partners.FindPartnerError(msg))
        return self.establish_partnership(recp, partner.allocation_id,
                                          alloc_id, substitute=partner)

    @manhole.expose()
    @replay.journaled
    def breakup(self, state, recp):
        '''breakup(recp) -> Order the agent to break the partnership with
        the given recipient'''
        recp = recipient.IRecipient(recp)
        partner = self.find_partner(recp)
        if partner:
            f = requester.say_goodbye(self, recp)
            f.add_callback(fiber.drop_param, self.remove_partner, partner)
            return f
        else:
            self.warning('We were trying to break up with agent recp %r.,'
                         'but aparently he is not our partner!.', recp)

    @replay.immutable
    def create_partner(self, state, partner_class, recp, allocation_id=None,
                       role=None, substitute=None):
        return state.partners.create(partner_class, recp, allocation_id, role,
                                     substitute)

    @replay.immutable
    def remove_partner(self, state, partner):
        return state.partners.remove(partner)

    @replay.mutable
    def partner_sent_notification(self, state, recp, notification_type,
                                  payload, sender):
        return state.partners.receive_notification(
            recp, notification_type, payload, sender)

    @manhole.expose()
    @replay.immutable
    def query_partners(self, state, name_or_class):
        '''query_partners(name_or_class) ->
              Query the partners by the relation name or partner class.'''
        return state.partners.query(name_or_class)

    @manhole.expose()
    @replay.immutable
    def query_partners_with_role(self, state, name, role):
        return state.partners.query_with_role(name, role)

    @replay.immutable
    def find_partner(self, state, recp_or_agent_id):
        return state.partners.find(recp_or_agent_id)

    @replay.immutable
    def query_partner_handler(self, state, partner_type, role=None):
        return state.partners.query_handler(partner_type, role)

    @manhole.expose()
    @replay.immutable
    def get_own_address(self, state):
        '''get_own_address() -> Return IRecipient representing the agent.'''
        return recipient.IRecipient(state.medium)

    @replay.immutable
    def initiate_protocol(self, state, *args, **kwargs):
        return state.medium.initiate_protocol(*args, **kwargs)

    @replay.immutable
    def retrying_protocol(self, state, *args, **kwargs):
        return state.medium.retrying_protocol(*args, **kwargs)

    @replay.immutable
    def periodic_protocol(self, state, *args, **kwargs):
        return state.medium.periodic_protocol(*args, **kwargs)

    @replay.immutable
    def initiate_task(self, state, *args, **kwargs):
        return state.medium.initiate_task(*args, **kwargs)

    @replay.immutable
    def retrying_task(self, state, *args, **kwargs):
        return state.medium.retrying_task(*args, **kwargs)

    @replay.immutable
    def register_interest(self, state, *args, **kwargs):
        return state.medium.register_interest(*args, **kwargs)

    @replay.mutable
    def preallocate_resource(self, state, **params):
        return state.resources.preallocate(**params)

    @replay.mutable
    def allocate_resource(self, state, **params):
        return state.resources.allocate(**params)

    @replay.immutable
    def check_allocation_exists(self, state, allocation_id):
        return state.resources.get_allocation(allocation_id)

    @manhole.expose()
    @replay.immutable
    def get_resource_usage(self, state):
        return state.resources.get_usage()

    @replay.immutable
    def list_resource(self, state):
        allocated = state.resources.allocated()
        totals = state.resources.get_totals()
        return totals, allocated

    @replay.mutable
    def confirm_allocation(self, state, allocation_id):
        return state.resources.confirm(allocation_id)

    @replay.immutable
    def allocation_used(self, state, allocation_id):
        '''
        Checks if allocation is used by any of the partners.
        If allocation does not exist returns False.
        @param allocation_id: ID of the allocation
        @returns: True/False
        '''
        return len(filter(lambda x: x.allocation_id == allocation_id,
                          state.partners.all)) > 0

    @replay.mutable
    def release_resource(self, state, allocation_id):
        return state.resources.release(allocation_id)

    @replay.mutable
    def premodify_allocation(self, state, allocation_id, **delta):
        return state.resources.premodify(allocation_id, **delta)

    @replay.mutable
    def apply_modification(self, state, change_id):
        return state.resources.apply_modification(change_id)

    @replay.mutable
    def release_modification(self, state, change_id):
        return state.resources.release_modification(change_id)

    @replay.immutable
    def get_document(self, state, doc_id):
        return fiber.wrap_defer(state.medium.get_document, doc_id)

    @replay.immutable
    def delete_document(self, state, doc):
        return fiber.wrap_defer(state.medium.delete_document, doc)

    @replay.immutable
    def query_view(self, state, factory, **options):
        return fiber.wrap_defer(state.medium.query_view, factory, **options)

    @replay.immutable
    def save_document(self, state, doc):
        return fiber.wrap_defer(state.medium.save_document, doc)

    @update_descriptor
    def update_descriptor(self, state, desc, method, *args, **kwargs):
        return method(desc, *args, **kwargs)

    @replay.journaled
    def discover_service(self, state, string_or_factory,
                         timeout=3, shard='lobby'):
        initiator = manager.DiscoverService(string_or_factory, timeout)
        recp = recipient.Broadcast(shard=shard,
                                   protocol_id=initiator.protocol_id)

        f = fiber.succeed(initiator)
        f.add_callback(self.initiate_protocol, recp)
        # this contract will always finish in expired state as it is blindly
        # rejecting all it gets
        f.add_callback(manager.ServiceDiscoveryManager.notify_finish)
        f.add_errback(self._expire_handler)
        return f

    @replay.immutable
    def call_next(self, state, method, *args, **kwargs):
        return state.medium.call_next(method, *args, **kwargs)

    @replay.immutable
    def call_later(self, state, time_left, method, *args, **kwargs):
        return state.medium.call_later(time_left, method, *args, **kwargs)

    @replay.immutable
    def cancel_delayed_call(self, state, call_id):
        state.medium.cancel_delayed_call(call_id)

    ### Private Methods ###

    def _expire_handler(self, fail):
        if fail.check(protocols.ProtocolFailed):
            return fail.value.args[0]
        else:
            fail.raiseException()
