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
from feat.test import common
from feat.agents.base import view
from feat.common import text_helper


class SomeView(view.BaseView):

    name = 'some_view'

    def map(doc):
        yield doc['_id'], doc['_id']


class ReducingView(view.BaseView):

    name = 'reducing_view'
    use_reduce = True

    def map(doc):
        yield doc['_id'], 1

    def reduce(keys, values):
        return len(values)


class TestDesignDocument(common.TestCase):

    def testGenerateDesignDoc(self):
        views = (SomeView, ReducingView, )
        doc = view.DesignDocument.generate_from_views(views)

        self.assertIsInstance(doc, view.DesignDocument)
        self.assertEquals(u'python', doc.language)
        self.assertEquals(2, len(doc.views))
        self.assertIn('some_view', doc.views)
        self.assertIn('map', doc.views['some_view'])
        expected = "def map(doc):\n    yield doc['_id'], doc['_id']"
        self.assertEqual(expected, doc.views['some_view']['map'])
        self.assertNotIn('reduce', doc.views['some_view'])

        self.assertIn('reducing_view', doc.views)
        self.assertIn('map', doc.views['reducing_view'])
        self.assertIn('reduce', doc.views['reducing_view'])
