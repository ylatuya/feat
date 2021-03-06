# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
from feat.agents.base import agent, view, descriptor, replay, document
from feat.test.integration import common
from feat.common.text_helper import format_block
from feat.common import defer


@document.register
class SomeDocument(document.Document):

    document_type = "test-document"
    document.field('value', None)


@view.register
class SummingView(view.BaseView):

    name = "sum"
    use_reduce = True

    def map(doc):
        if doc['.type'] == 'test-document':
            yield None, doc['value']

    reduce = "_sum"


@view.register
class VerboseView(view.FormatableView):

    name = "verbose"
    view.field('result', None)

    def map(doc):
        if doc['.type'] == 'test-document':
            yield None, dict(result=doc['value'])


@descriptor.register('querying-view-agent')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('querying-view-agent')
class Agent(agent.BaseAgent):

    @replay.journaled
    def query(self, state, **options):
        return self.query_view(SummingView, **options)

    @replay.journaled
    def query_verbose(self, state, **options):
        return self.query_view(VerboseView, **options)

    @replay.immutable
    def save_doc(self, state, value):
        doc = SomeDocument(value=value)
        return state.medium.save_document(doc)


class ViewTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
        desc = descriptor_factory('querying-view-agent')
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        medium = agency.start_agent(desc)
        wait_for_idle()
        """)
        return self.process(setup)

    @defer.inlineCallbacks
    def testItWorks(self):
        agent = self.get_local('medium').get_agent()
        resp = yield agent.query()
        self.assertIsInstance(resp, list)
        self.assertFalse(resp)

        yield agent.save_doc(2)
        resp = yield agent.query()
        self.assertIsInstance(resp, list)
        self.assertEqual([2], resp)

        resp = yield agent.query_verbose()
        self.assertIsInstance(resp, list)
        self.assertIsInstance(resp[0], VerboseView)
        self.assertEqual(2, resp[0].result)

        yield agent.save_doc(5)
        resp = yield agent.query()
        self.assertIsInstance(resp, list)
        self.assertEqual([7], resp)
        resp = yield agent.query(reduce=False)
        self.assertIsInstance(resp, list)
        self.assertEqual(set([5, 2]), set(resp))

        resp = yield agent.query_verbose()
        self.assertIsInstance(resp, list)
        self.assertIsInstance(resp[0], VerboseView)
        self.assertIsInstance(resp[1], VerboseView)
        self.assertIn(resp[0].result, (2, 5))
        self.assertIn(resp[1].result, (2, 5))
