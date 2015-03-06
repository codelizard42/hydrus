import collections
import HydrusConstants as HC
import HydrusImageHandling
import os
import TestConstants
import unittest
import wx

class TestImageHandling( unittest.TestCase ):
	
	def test_phash( self ):
		
		phash = HydrusImageHandling.GeneratePerceptualHash( HC.STATIC_DIR + os.path.sep + 'hydrus.png' )
		
		self.assertEqual( phash, '\xb0\x08\x83\xb2\x08\x0b8\x08' )
		
