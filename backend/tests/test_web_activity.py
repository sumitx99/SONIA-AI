import asyncio
import unittest
from unittest.mock import patch
from app.mcp_client import agent
from app.services.web_activity import WebActivity, safe_url

class WebActivityTests(unittest.TestCase):
    def test_tool_events_update_same_card_and_do_not_expose_raw_results(self):
        activity=WebActivity()
        running=activity.event({'id':'s1','toolType':'GOOGLE_SEARCH_WEB','args':{'queries':['AI Studio pricing'],'secret':'private'}})
        done=activity.event({'id':'s1','toolType':'GOOGLE_SEARCH_WEB','response':{'raw':'private'}},response=True)
        self.assertEqual(running['id'],done['id'])
        self.assertEqual((running['status'],done['status']),('running','done'))
        self.assertEqual(done['arguments'],{'queries':['AI Studio pricing']})
        self.assertNotIn('private',str(done))
        self.assertIsNone(activity.event({'toolType':'UNKNOWN'}))

    def test_rejects_unsafe_links(self):
        for url in ['javascript:alert(1)','https://user:secret@example.com',None,'broken']:
            self.assertIsNone(safe_url(url))
        self.assertEqual(safe_url('https://ai.google.dev/pricing'),'https://ai.google.dev/pricing')

    def test_progress_and_sources_precede_answer_and_thoughts_are_not_exposed(self):
        parts=[{'toolCall':{'id':'s1','toolType':'GOOGLE_SEARCH_WEB','args':{'query':'AI Studio pricing'}}},
               {'thought':True,'text':'Private reasoning'},
               {'toolResponse':{'id':'s1','toolType':'GOOGLE_SEARCH_WEB','response':{}}},
               {'groundingMetadata':{'webSearchQueries':['AI Studio pricing'],'groundingChunks':[{'web':{'uri':'https://ai.google.dev/pricing','title':'Official pricing'}}]}},
               {'urlContextMetadata':{'urlMetadata':[{'retrievedUrl':'https://ai.google.dev/pricing','urlRetrievalStatus':'URL_RETRIEVAL_STATUS_SUCCESS'}]}},
               {'text':'The answer'}]
        async def run(): return [event async for event in agent.answer_with_tools('user1','query','ctx',[],{})]
        with patch.object(agent,'stream_gemini_parts',return_value=iter(parts)):
            events=asyncio.run(run())
        self.assertEqual(events[0][1]['status'],'running')
        self.assertEqual(events[1][1]['status'],'done')
        self.assertLess(next(i for i,e in enumerate(events) if e[0]=='sources'),next(i for i,e in enumerate(events) if e[0]=='delta'))
        self.assertNotIn('Private reasoning',str(events))
        self.assertTrue(any(e[0]=='tool_call' and e[1]['tool']=='url_context' for e in events))

    def test_no_fake_search_for_plain_answer(self):
        async def run(): return [event async for event in agent.answer_with_tools('user1','Hello','',[],{})]
        with patch.object(agent,'stream_gemini_parts',return_value=iter([{'text':'Hello'}])):
            self.assertEqual(asyncio.run(run()),[('delta',{'text':'Hello'})])
