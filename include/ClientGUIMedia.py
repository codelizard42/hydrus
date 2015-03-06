import HydrusConstants as HC
import ClientConstants as CC
import ClientGUICommon
import ClientGUIDialogs
import ClientGUIDialogsManage
import ClientGUICanvas
import ClientGUIMixins
import collections
import HydrusTags
import HydrusThreading
import itertools
import os
import random
import subprocess
import threading
import time
import traceback
import wx
import yaml

# Option Enums

ID_TIMER_ANIMATION = wx.NewId()

# Sizer Flags

FLAGS_NONE = wx.SizerFlags( 0 )

FLAGS_SMALL_INDENT = wx.SizerFlags( 0 ).Border( wx.ALL, 2 )

FLAGS_EXPAND_PERPENDICULAR = wx.SizerFlags( 0 ).Border( wx.ALL, 2 ).Expand()
FLAGS_EXPAND_BOTH_WAYS = wx.SizerFlags( 2 ).Border( wx.ALL, 2 ).Expand()
FLAGS_EXPAND_DEPTH_ONLY = wx.SizerFlags( 2 ).Border( wx.ALL, 2 ).Align( wx.ALIGN_CENTER_VERTICAL )

FLAGS_EXPAND_SIZER_PERPENDICULAR = wx.SizerFlags( 0 ).Expand()
FLAGS_EXPAND_SIZER_BOTH_WAYS = wx.SizerFlags( 2 ).Expand()
FLAGS_EXPAND_SIZER_DEPTH_ONLY = wx.SizerFlags( 2 ).Align( wx.ALIGN_CENTER_VERTICAL )

FLAGS_BUTTON_SIZER = wx.SizerFlags( 0 ).Align( wx.ALIGN_RIGHT )
FLAGS_LONE_BUTTON = wx.SizerFlags( 0 ).Border( wx.ALL, 2 ).Align( wx.ALIGN_RIGHT )

FLAGS_MIXED = wx.SizerFlags( 0 ).Border( wx.ALL, 2 ).Align( wx.ALIGN_CENTER_VERTICAL )

def AddFileServiceKeysToMenu( menu, file_service_keys, phrase, action ):
	
	services_manager = HC.app.GetManager( 'services' )
	
	if len( file_service_keys ) == 1:
		
		( file_service_key, ) = file_service_keys
		
		if action == CC.ID_NULL: id = CC.ID_NULL
		else: id = CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( action, file_service_key )
		
		file_service = services_manager.GetService( file_service_key )
		
		menu.Append( id, phrase + ' ' + file_service.GetName() )
		
	else:
		
		submenu = wx.Menu()
		
		for file_service_key in file_service_keys: 
			
			if action == CC.ID_NULL: id = CC.ID_NULL
			else: id = CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( action, file_service_key )
			
			file_service = services_manager.GetService( file_service_key )
			
			submenu.Append( id, file_service.GetName() )
			
		
		menu.AppendMenu( CC.ID_NULL, phrase + u'\u2026', submenu )
		
	
class MediaPanel( ClientGUIMixins.ListeningMediaList, wx.ScrolledWindow ):
	
	def __init__( self, parent, page_key, file_service_key, media_results ):
		
		wx.ScrolledWindow.__init__( self, parent, size = ( 0, 0 ), style = wx.BORDER_SUNKEN )
		ClientGUIMixins.ListeningMediaList.__init__( self, file_service_key, media_results )
		
		self.SetBackgroundColour( wx.WHITE )
		
		#self.SetDoubleBuffered( True )
		
		self.SetScrollRate( 0, 50 )
		
		self._page_key = page_key
		
		self._focussed_media = None
		self._shift_focussed_media = None
		
		self._selected_media = set()
		
		HC.pubsub.sub( self, 'AddMediaResults', 'add_media_results' )
		HC.pubsub.sub( self, 'SetFocussedMedia', 'set_focus' )
		HC.pubsub.sub( self, 'PageHidden', 'page_hidden' )
		HC.pubsub.sub( self, 'PageShown', 'page_shown' )
		HC.pubsub.sub( self, 'Collect', 'collect_media' )
		HC.pubsub.sub( self, 'Sort', 'sort_media' )
		HC.pubsub.sub( self, 'FileDumped', 'file_dumped' )
		HC.pubsub.sub( self, 'RemoveMedia', 'remove_media' )
		
		self._PublishSelectionChange()
		
	
	def _Archive( self ):
		
		hashes = self._GetSelectedHashes( CC.DISCRIMINANT_INBOX )
		
		if len( hashes ) > 0:
			
			if len( hashes ) > 1:
				
				message = 'Archive ' + HC.ConvertIntToPrettyString( len( hashes ) ) + ' files?'
				
				with ClientGUIDialogs.DialogYesNo( self, message ) as dlg:
					
					if dlg.ShowModal() != wx.ID_YES: return
					
				
			
			HC.app.Write( 'content_updates', { HC.LOCAL_FILE_SERVICE_KEY : [ HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_ARCHIVE, hashes ) ] } )
			
		
	
	def _CopyBMPToClipboard( self ):
		
		media = self._focussed_media.GetDisplayMedia()
		
		HC.pubsub.pub( 'clipboard', 'bmp', media )
		
	
	def _CopyHashToClipboard( self ):
		
		hex_hash = self._focussed_media.GetDisplayMedia().GetHash().encode( 'hex' )
		
		HC.pubsub.pub( 'clipboard', 'text', hex_hash )
		
	
	def _CopyHashesToClipboard( self ):
		
		hex_hashes = os.linesep.join( [ hash.encode( 'hex' ) for hash in self._GetSelectedHashes() ] )
		
		HC.pubsub.pub( 'clipboard', 'text', hex_hashes )
		
	
	def _CopyLocalUrlToClipboard( self ):
		
		local_url = 'http://127.0.0.1:' + str( HC.options[ 'local_port' ] ) + '/file?hash=' + self._focussed_media.GetDisplayMedia().GetHash().encode( 'hex' )
		
		HC.pubsub.pub( 'clipboard', 'text', local_url )
		
	
	def _CopyPathToClipboard( self ):
	
		display_media = self._focussed_media.GetDisplayMedia()
		
		path = CC.GetFilePath( display_media.GetHash(), display_media.GetMime() )
		
		HC.pubsub.pub( 'clipboard', 'text', path )
		
	
	def _CustomFilter( self ):
		
		with ClientGUIDialogs.DialogSetupCustomFilterActions( self ) as dlg:
			
			if dlg.ShowModal() == wx.ID_OK:
				
				actions = dlg.GetActions()
				
				media_results = self.GenerateMediaResults( discriminant = CC.DISCRIMINANT_LOCAL, selected_media = set( self._selected_media ) )
				
				if len( media_results ) > 0:
					
					try: ClientGUICanvas.CanvasFullscreenMediaListCustomFilter( self.GetTopLevelParent(), self._page_key, self._file_service_key, media_results, actions )
					except: wx.MessageBox( traceback.format_exc() )
					
				
			
		
	
	def _Delete( self, file_service_key ):
		
		if file_service_key == HC.LOCAL_FILE_SERVICE_KEY:
			
			hashes = self._GetSelectedHashes( CC.DISCRIMINANT_LOCAL )
			
			num_to_delete = len( hashes )
			
			if num_to_delete:
				
				if num_to_delete == 1: message = 'Are you sure you want to delete this file?'
				else: message = 'Are you sure you want to delete these ' + HC.ConvertIntToPrettyString( num_to_delete ) + ' files?'
				
				with ClientGUIDialogs.DialogYesNo( self, message ) as dlg:
					
					if dlg.ShowModal() == wx.ID_YES:
						
						self.SetFocussedMedia( self._page_key, None )
						
						try: HC.app.Write( 'content_updates', { file_service_key : [ HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_DELETE, hashes ) ] } )
						except: wx.MessageBox( traceback.format_exc() )
						
					
				
			
		else:
			
			hashes = self._GetSelectedHashes()
			
			content_update = HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_PETITION, ( hashes, 'admin' ) )
			
			service_keys_to_content_updates = { file_service_key : ( content_update, ) }
			
			HC.app.Write( 'content_updates', service_keys_to_content_updates )
			
		
	
	def _DeselectSelect( self, media_to_deselect, media_to_select ):
		
		if len( media_to_deselect ) > 0:
			
			for m in media_to_deselect: m.Deselect()
			
			self._RedrawMediaIfLoaded( media_to_deselect )
			
			self._selected_media.difference_update( media_to_deselect )
			
		
		if len( media_to_select ) > 0:
			
			for m in media_to_select: m.Select()
			
			self._RedrawMediaIfLoaded( media_to_select )
			
			self._selected_media.update( media_to_select )
			
		
		self._PublishSelectionChange()
		
	
	def _FullScreen( self, first_media = None ):
		
		media_results = self.GenerateMediaResults( discriminant = CC.DISCRIMINANT_LOCAL )
		
		if len( media_results ) > 0:
			
			if first_media is None and self._focussed_media is not None: first_media = self._focussed_media
			
			if first_media is not None and first_media.GetLocationsManager().HasLocal(): first_hash = first_media.GetDisplayMedia().GetHash()
			else: first_hash = None
			
			ClientGUICanvas.CanvasFullscreenMediaListBrowser( self.GetTopLevelParent(), self._page_key, self._file_service_key, media_results, first_hash )
			
		
	
	def _Filter( self ):
		
		media_results = self.GenerateMediaResults( discriminant = CC.DISCRIMINANT_LOCAL, selected_media = set( self._selected_media ) )
		
		if len( media_results ) > 0:
			
			try: ClientGUICanvas.CanvasFullscreenMediaListFilterInbox( self.GetTopLevelParent(), self._page_key, self._file_service_key, media_results )
			except: wx.MessageBox( traceback.format_exc() )
			
		
	
	def _GetNumSelected( self ): return sum( [ media.GetNumFiles() for media in self._selected_media ] )
	
	def _GetPrettyStatus( self ):
		
		num_files = sum( [ media.GetNumFiles() for media in self._sorted_media ] )
		
		num_selected = self._GetNumSelected()
		
		pretty_total_size = self._GetPrettyTotalSelectedSize()
		
		if num_selected == 0:
			
			if num_files == 1: s = '1 file'
			else: s = HC.ConvertIntToPrettyString( num_files ) + ' files'
			
		elif num_selected == 1: s = '1 of ' + HC.ConvertIntToPrettyString( num_files ) + ' files selected, ' + pretty_total_size
		else:
			
			num_inbox = sum( ( media.GetNumInbox() for media in self._selected_media ) )
			
			if num_inbox == num_selected: inbox_phrase = 'all in inbox, '
			elif num_inbox == 0: inbox_phrase = 'all archived, '
			else: inbox_phrase = HC.ConvertIntToPrettyString( num_inbox ) + ' in inbox and ' + HC.ConvertIntToPrettyString( num_selected - num_inbox ) + ' archived, '
			
			s = HC.ConvertIntToPrettyString( num_selected ) + ' of ' + HC.ConvertIntToPrettyString( num_files ) + ' files selected, ' + inbox_phrase + 'totalling ' + pretty_total_size
			
		
		return s
		
	
	def _GetPrettyTotalSelectedSize( self ):
		
		total_size = sum( [ media.GetSize() for media in self._selected_media ] )
		
		unknown_size = False in ( media.IsSizeDefinite() for media in self._selected_media )
		
		if total_size == 0:
			
			if unknown_size: return 'unknown size'
			else: return HC.ConvertIntToBytes( 0 )
			
		else:
			
			if unknown_size: return HC.ConvertIntToBytes( total_size ) + ' + some unknown size'
			else: return HC.ConvertIntToBytes( total_size )
			
		
	
	def _GetSelectedHashes( self, discriminant = None, not_uploaded_to = None ):
		
		result = set()
		
		for media in self._selected_media: result.update( media.GetHashes( discriminant, not_uploaded_to ) )
		
		return result
		
	
	def _GetSimilarTo( self ):
		
		if self._focussed_media is not None:
			
			hash = self._focussed_media.GetDisplayMedia().GetHash()
			
			HC.pubsub.pub( 'new_similar_to', self._file_service_key, hash )
			
		
	
	def _HitMedia( self, media, ctrl, shift ):
		
		if media is None:
			
			if not ctrl and not shift:
				
				self._Select( 'none' )
				self._SetFocussedMedia( None )
				self._shift_focussed_media = None
				
			
		else:
			
			if ctrl:
				
				if media.IsSelected():
					
					self._DeselectSelect( ( media, ), () )
					
					if self._focussed_media == media: self._SetFocussedMedia( None )
					
				else:
					
					self._DeselectSelect( (), ( media, ) )
					
					if self._focussed_media is None: self._SetFocussedMedia( media )
					
				
				self._shift_focussed_media = None
				
			elif shift and self._focussed_media is not None:
				
				if self._shift_focussed_media is None: self._shift_focussed_media = self._focussed_media
				
				start_index = self._sorted_media.index( self._shift_focussed_media )
				
				end_index = self._sorted_media.index( media )
				
				if start_index < end_index: media_i_want_selected_at_the_end = set( self._sorted_media[ start_index : end_index + 1 ] )
				else: media_i_want_selected_at_the_end = set( self._sorted_media[ end_index : start_index + 1 ] )
				
				self._DeselectSelect( self._selected_media - media_i_want_selected_at_the_end, media_i_want_selected_at_the_end - self._selected_media )
				
				self._SetFocussedMedia( media )
				
			else:
				
				if not media.IsSelected(): self._DeselectSelect( self._selected_media, ( media, ) )
				else: self._PublishSelectionChange()
				
				self._SetFocussedMedia( media )
				self._shift_focussed_media = None
				
			
		
	
	def _Inbox( self ):
		
		hashes = self._GetSelectedHashes( CC.DISCRIMINANT_ARCHIVE )
		
		if len( hashes ) > 0:
			
			if len( hashes ) > 1:
				
				message = 'Send ' + HC.ConvertIntToPrettyString( len( hashes ) ) + ' files to inbox?'
				
				with ClientGUIDialogs.DialogYesNo( self, message ) as dlg:
					
					if dlg.ShowModal() != wx.ID_YES: return
					
				
			
			HC.app.Write( 'content_updates', { HC.LOCAL_FILE_SERVICE_KEY : [ HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_INBOX, hashes ) ] } )
			
		
	
	def _ManageRatings( self ):
		
		if len( self._selected_media ) > 0:
			
			if len( HC.app.GetManager( 'services' ).GetServices( HC.RATINGS_SERVICES ) ) > 0:
				
				try:
					
					flat_media = []
					
					for media in self._selected_media:
						
						if media.IsCollection(): flat_media.extend( media.GetFlatMedia() )
						else: flat_media.append( media )
						
					
					with ClientGUIDialogsManage.DialogManageRatings( None, flat_media ) as dlg: dlg.ShowModal()
					
					self.SetFocus()
					
				except: wx.MessageBox( traceback.format_exc() )
				
			
		
	
	def _ManageTags( self ):
		
		if len( self._selected_media ) > 0:
			
			with ClientGUIDialogsManage.DialogManageTags( self.GetTopLevelParent(), self._file_service_key, self._selected_media ) as dlg: dlg.ShowModal()
			
			self.SetFocus()
			
		
	
	def _ModifyUploaders( self, file_service_key ):
		
		hashes = self._GetSelectedHashes()
		
		if hashes is not None and len( hashes ) > 0:   
			
			with ClientGUIDialogs.DialogModifyAccounts( self, file_service_key, [ HC.AccountIdentifier( hash = hash ) for hash in hashes ] ) as dlg: dlg.ShowModal()
			
			self.SetFocus()
			
		
	
	def _NewThreadDumper( self ):
		
		# can't do normal _getselectedhashes because we want to keep order!
		
		args = [ media.GetHashes( CC.DISCRIMINANT_LOCAL ) for media in self._selected_media ]
		
		hashes = [ h for h in itertools.chain( *args ) ]
		
		if len( hashes ) > 0: HC.pubsub.pub( 'new_thread_dumper', hashes )
		
	
	def _OpenExternally( self ):
		
		if self._focussed_media is not None:
			
			hash = self._focussed_media.GetHash()
			mime = self._focussed_media.GetMime()
			
			path = CC.GetFilePath( hash, mime )
			
			HC.LaunchFile( path )
			
		
	
	def _PetitionFiles( self, file_service_key ):
		
		hashes = self._GetSelectedHashes()
		
		if hashes is not None and len( hashes ) > 0:
			
			file_service = HC.app.GetManager( 'services' ).GetService( file_service_key )
			
			if len( hashes ) == 1: message = 'Enter a reason for this file to be removed from ' + file_service.GetName() + '.'
			else: message = 'Enter a reason for these ' + HC.ConvertIntToPrettyString( len( hashes ) ) + ' files to be removed from ' + file_service.GetName() + '.'
			
			with ClientGUIDialogs.DialogTextEntry( self, message ) as dlg:
				
				if dlg.ShowModal() == wx.ID_OK:
					
					content_update = HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_PETITION, ( hashes, dlg.GetValue() ) )
					
					service_keys_to_content_updates = { file_service_key : ( content_update, ) }
					
					HC.app.Write( 'content_updates', service_keys_to_content_updates )
					
				
			
			self.SetFocus()
			
		
	
	def _PublishSelectionChange( self, force_reload = False ):
		
		if len( self._selected_media ) == 0: tags_media = self._sorted_media
		else: tags_media = self._selected_media
		
		HC.pubsub.pub( 'new_tags_selection', self._page_key, tags_media, force_reload = force_reload )
		HC.pubsub.pub( 'new_page_status', self._page_key, self._GetPrettyStatus() )
		
	
	def _RatingsFilter( self, service_key ):
		
		if service_key is None:
			
			service_key = ClientGUIDialogs.SelectServiceKey( service_types = ( HC.LOCAL_RATING_LIKE, HC.LOCAL_RATING_NUMERICAL ) )
			
			if service_key is None: return
			
		
		media_results = self.GenerateMediaResults( discriminant = CC.DISCRIMINANT_LOCAL, selected_media = set( self._selected_media ), unrated = service_key )
		
		if len( media_results ) > 0:
			
			try:
				
				service = HC.app.GetManager( 'services' ).GetService( service_key )
				
				if service.GetServiceType() == HC.LOCAL_RATING_LIKE: ClientGUICanvas.RatingsFilterFrameLike( self.GetTopLevelParent(), self._page_key, service_key, media_results )
				elif service.GetServiceType() == HC.LOCAL_RATING_NUMERICAL: ClientGUICanvas.RatingsFilterFrameNumerical( self.GetTopLevelParent(), self._page_key, service_key, media_results )
				
			except: wx.MessageBox( traceback.format_exc() )
			
		
	
	def _RecalculateVirtualSize( self ): pass
	
	def _RedrawMediaIfLoaded( self, media ): pass
	
	def _RescindPetitionFiles( self, file_service_key ):
		
		hashes = self._GetSelectedHashes()
		
		if hashes is not None and len( hashes ) > 0:   
			
			HC.app.Write( 'content_updates', { file_service_key : [ HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_RESCIND_PETITION, hashes ) ] } )
			
		
	
	def _RescindUploadFiles( self, file_service_key ):
		
		hashes = self._GetSelectedHashes()
		
		if hashes is not None and len( hashes ) > 0:   
			
			HC.app.Write( 'content_updates', { file_service_key : [ HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_RESCIND_PENDING, hashes ) ] } )
			
		
	
	def _Select( self, select_type ):
		
		if select_type == 'all': self._DeselectSelect( [], self._sorted_media )
		else:
			
			if select_type == 'invert':
				
				( media_to_deselect, media_to_select ) = ( self._selected_media, set( self._sorted_media ) - self._selected_media )
				
			elif select_type == 'none': ( media_to_deselect, media_to_select ) = ( self._selected_media, [] )
			else:
				
				inbox_media = { m for m in self._sorted_media if m.HasInbox() }
				archive_media = { m for m in self._sorted_media if m not in inbox_media }
				
				if select_type == 'inbox':
					
					media_to_deselect = [ m for m in archive_media if m in self._selected_media ]
					media_to_select = [ m for m in inbox_media if m not in self._selected_media ]
					
				elif select_type == 'archive':
					
					media_to_deselect = [ m for m in inbox_media if m in self._selected_media ]
					media_to_select = [ m for m in archive_media if m not in self._selected_media ]
					
				
			
			if self._focussed_media in media_to_deselect: self._SetFocussedMedia( None )
			
			self._DeselectSelect( media_to_deselect, media_to_select )
			
			self._shift_focussed_media = None
			
		
	
	def _SetFocussedMedia( self, media ):
		
		self._focussed_media = media
		
		HC.pubsub.pub( 'focus_changed', self._page_key, media )
		
	
	def _ShareOnLocalBooru( self ):
		
		if len( self._selected_media ) > 0:
			
			share_key = os.urandom( 32 )
			
			name = ''
			text = ''
			timeout = HC.GetNow() + 60 * 60 * 24
			hashes = self._GetSelectedHashes()
			
			with ClientGUIDialogs.DialogInputLocalBooruShare( self, share_key, name, text, timeout, hashes, new_share = True ) as dlg:
				
				if dlg.ShowModal() == wx.ID_OK:
					
					( share_key, name, text, timeout, hashes ) = dlg.GetInfo()
					
					info = {}
					
					info[ 'name' ] = name
					info[ 'text' ] = text
					info[ 'timeout' ] = timeout
					info[ 'hashes' ] = hashes
					
					HC.app.Write( 'local_booru_share', share_key, info )
					
				
			
			self.SetFocus()
			
		
	
	def _ShowSelectionInNewQueryPage( self ):
		
		hashes = self._GetSelectedHashes()
		
		if hashes is not None and len( hashes ) > 0:
			
			media_results = HC.app.Read( 'media_results', self._file_service_key, hashes )
			
			hashes_to_media_results = { media_result.GetHash() : media_result for media_result in media_results }
			
			sorted_flat_media = self.GetFlatMedia()
			
			sorted_media_results = [ hashes_to_media_results[ media.GetHash() ] for media in sorted_flat_media if media.GetHash() in hashes_to_media_results ]
			
			HC.pubsub.pub( 'new_page_query', self._file_service_key, initial_media_results = sorted_media_results )
			
		
	
	def _UploadFiles( self, file_service_key ):
		
		hashes = self._GetSelectedHashes( not_uploaded_to = file_service_key )
		
		if hashes is not None and len( hashes ) > 0:   
			
			HC.app.Write( 'content_updates', { file_service_key : [ HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_PENDING, hashes ) ] } )
			
		
	
	def AddMediaResults( self, page_key, media_results, append = True ):
		
		if page_key == self._page_key: return ClientGUIMixins.ListeningMediaList.AddMediaResults( self, media_results, append = append )
		
	
	def Archive( self, hashes ):
		
		ClientGUIMixins.ListeningMediaList.Archive( self, hashes )
		
		affected_media = self._GetMedia( hashes )
		
		if len( affected_media ) > 0: self._RedrawMediaIfLoaded( affected_media )
		
		self._PublishSelectionChange()
		
		if self._focussed_media is not None: self._HitMedia( self._focussed_media, False, False )
		
	
	def Collect( self, page_key, collect_by = -1 ):
		
		if page_key == self._page_key:
			
			self._Select( 'none' )
			
			ClientGUIMixins.ListeningMediaList.Collect( self, collect_by )
			
			self._RecalculateVirtualSize()
			
			# no refresh needed since the sort call that always comes after will do it
			
		
	
	def FileDumped( self, page_key, hash, status ):
		
		if page_key == self._page_key:
			
			media = self._GetMedia( { hash } )
			
			for m in media: m.Dumped( status )
			
			self._RedrawMediaIfLoaded( media )
			
		
	
	def PageHidden( self, page_key ):
		
		if page_key == self._page_key: HC.pubsub.pub( 'focus_changed', self._page_key, None )
		
	
	def PageShown( self, page_key ):
		
		if page_key == self._page_key:
			
			HC.pubsub.pub( 'focus_changed', self._page_key, self._focussed_media )
			
			self._PublishSelectionChange()
			
		
	
	def ProcessContentUpdates( self, service_keys_to_content_updates ):
		
		ClientGUIMixins.ListeningMediaList.ProcessContentUpdates( self, service_keys_to_content_updates )
		
		force_reload = False
		
		for ( service_key, content_updates ) in service_keys_to_content_updates.items():
			
			for content_update in content_updates:
				
				( data_type, action, row ) = content_update.ToTuple()
				
				hashes = content_update.GetHashes()
				
				affected_media = self._GetMedia( hashes )
				
				if len( affected_media ) > 0:
					
					self._RedrawMediaIfLoaded( affected_media )
					
					force_reload = True
					
				
			
		
		self._PublishSelectionChange( force_reload = force_reload )
		
		if self._focussed_media is not None: self._HitMedia( self._focussed_media, False, False )
		
	
	def ProcessServiceUpdates( self, service_keys_to_service_updates ):
		
		ClientGUIMixins.ListeningMediaList.ProcessServiceUpdates( self, service_keys_to_service_updates )
		
		for ( service_key, service_updates ) in service_keys_to_service_updates.items():
			
			for service_update in service_updates:
				
				( action, row ) = service_update.ToTuple()
				
				if action in ( HC.SERVICE_UPDATE_DELETE_PENDING, HC.SERVICE_UPDATE_RESET ): self._RecalculateVirtualSize()
				
				self._PublishSelectionChange( force_reload = True )
				
			
		
	
	def RemoveMedia( self, page_key, hashes ):
		
		if page_key == self._page_key:
			
			media = self._GetMedia( hashes )
			
			self._RemoveMedia( media, {} )
			
		
	
	def SetFocussedMedia( self, page_key, media ): pass
	
	def Sort( self, page_key, sort_by = None ):
		
		if page_key == self._page_key: ClientGUIMixins.ListeningMediaList.Sort( self, sort_by )
		
		HC.pubsub.pub( 'sorted_media_pulse', self._page_key, self._sorted_media )
		
	
class MediaPanelNoQuery( MediaPanel ):
		
	def __init__( self, parent, page_key, file_service_key ): MediaPanel.__init__( self, parent, page_key, file_service_key, [] )
		
	def _GetPrettyStatus( self ): return 'No query'
		
	def GetSortedMedia( self ): return None
		
class MediaPanelLoading( MediaPanel ):
		
	def __init__( self, parent, page_key, file_service_key ):
		
		self._current = None
		self._max = None
		
		MediaPanel.__init__( self, parent, page_key, file_service_key, [] )
		
		HC.pubsub.sub( self, 'SetNumQueryResults', 'set_num_query_results' )
		
	
	def _GetPrettyStatus( self ):
		
		s = u'Loading\u2026'
		
		if self._current is not None:
		
			s += ' ' + HC.ConvertIntToPrettyString( self._current )
		
			if self._max is not None:
		
				s += ' of ' + HC.ConvertIntToPrettyString( self._max )
		
			
		
		return s
		
	
	def GetSortedMedia( self ): return None
		
	def SetNumQueryResults( self, current, max ):
		
		self._current = current
		
		self._max = max
		
		self._PublishSelectionChange()
		
	
class MediaPanelThumbnails( MediaPanel ):
	
	def __init__( self, parent, page_key, file_service_key, media_results, refreshable = True ):
		
		MediaPanel.__init__( self, parent, page_key, file_service_key, media_results )
		
		self._refreshable = refreshable
		
		self._last_client_size = ( 0, 0 )
		self._num_columns = 1
		
		self._client_bmp = wx.EmptyBitmap( 0, 0 )
		self._clean_canvas_pages = {}
		self._dirty_canvas_pages = []
		self._num_rows_per_canvas_page = 1
		
		self._timer_animation = wx.Timer( self, ID_TIMER_ANIMATION )
		self._thumbnails_being_faded_in = {}
		
		self._thumbnail_span_dimensions = CC.AddPaddingToDimensions( HC.options[ 'thumbnail_dimensions' ], ( CC.THUMBNAIL_BORDER + CC.THUMBNAIL_MARGIN ) * 2 )
		
		( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
		
		self.SetScrollRate( 0, thumbnail_span_height )
		
		self.Bind( wx.EVT_LEFT_DOWN, self.EventSelection )
		self.Bind( wx.EVT_RIGHT_DOWN, self.EventShowMenu )
		self.Bind( wx.EVT_LEFT_DCLICK, self.EventMouseFullScreen )
		self.Bind( wx.EVT_MIDDLE_DOWN, self.EventMouseFullScreen )
		self.Bind( wx.EVT_PAINT, self.EventPaint )
		self.Bind( wx.EVT_SIZE, self.EventResize )
		self.Bind( wx.EVT_TIMER, self.TIMEREventAnimation, id = ID_TIMER_ANIMATION )
		self.Bind( wx.EVT_ERASE_BACKGROUND, self.EventEraseBackground )
		
		self.Bind( wx.EVT_KEY_DOWN, self.EventKeyDown )
		
		self.Bind( wx.EVT_MENU, self.EventMenu )
		
		self.RefreshAcceleratorTable()
		
		HC.pubsub.sub( self, 'NewThumbnails', 'new_thumbnails' )
		HC.pubsub.sub( self, 'ThumbnailsResized', 'thumbnail_resize' )
		HC.pubsub.sub( self, 'RefreshAcceleratorTable', 'notify_new_options' )
		HC.pubsub.sub( self, 'WaterfallThumbnail', 'waterfall_thumbnail' )
		
	
	def _CalculateVisiblePageIndices( self ):
		
		( xUnit, yUnit ) = self.GetScrollPixelsPerUnit()
		
		y_start = self._GetYStart()
		
		y_offset = y_start * yUnit
		
		( client_width, client_height ) = self.GetClientSize()
		
		( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
		
		page_height = self._num_rows_per_canvas_page * thumbnail_span_height
		
		page_indices = set()
		
		page_indices.add( y_offset / page_height )
		page_indices.add( ( y_offset + client_height ) / page_height )
		
		page_indices = list( page_indices )
		
		page_indices.sort()
		
		return page_indices
		
	
	def _DirtyAllPages( self ):
		
		for ( index, bmp ) in self._clean_canvas_pages.items(): self._dirty_canvas_pages.append( bmp )
		
		self._clean_canvas_pages = {}
		
		self.Refresh()
		
	
	def _DrawCanvasPage( self, page_index, bmp ):
		
		( bmp_width, bmp_height ) = bmp.GetSize()
		
		dc = wx.MemoryDC( bmp )
		
		dc.SetBrush( wx.Brush( wx.Colour( *HC.options[ 'gui_colours' ][ 'thumbgrid_background' ] ) ) )
		
		dc.SetPen( wx.TRANSPARENT_PEN )
		
		dc.DrawRectangle( 0, 0, bmp_width, bmp_height )
		
		#
		
		num_thumbnails_per_page = self._num_columns * self._num_rows_per_canvas_page
		
		start_index = num_thumbnails_per_page * page_index
		
		if start_index <= len( self._sorted_media ):
			
			end_index = min( len( self._sorted_media ), start_index + num_thumbnails_per_page )
			
			( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
			
			thumbnails_to_render_later = []
			
			for thumbnail_index in range( start_index, end_index ):
				
				thumbnail = self._sorted_media[ thumbnail_index ]
				
				hash = thumbnail.GetDisplayMedia().GetHash()
				
				self._StopFading( hash )
				
				if thumbnail.IsLoaded():
					
					thumbnail_col = thumbnail_index % self._num_columns
					
					thumbnail_row = thumbnail_index / self._num_columns
					
					x = thumbnail_col * thumbnail_span_width + CC.THUMBNAIL_MARGIN
					
					y = ( thumbnail_row - ( page_index * self._num_rows_per_canvas_page ) ) * thumbnail_span_height + CC.THUMBNAIL_MARGIN
					
					dc.DrawBitmap( thumbnail.GetBmp(), x, y )
					
				else: thumbnails_to_render_later.append( thumbnail )
				
			
			HC.app.GetThumbnailCache().Waterfall( self._page_key, thumbnails_to_render_later )
			
		
	
	def _DrawThumbnail( self, thumbnail_index ):
		
		page_index = self._GetPageIndexFromThumbnailIndex( thumbnail_index )
		
		if page_index in self._clean_canvas_pages:
			
			canvas_bmp = self._clean_canvas_pages[ page_index ]
	
			( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
			
			thumbnail = self._sorted_media[ thumbnail_index ]
			
			thumbnail_col = thumbnail_index % self._num_columns
			
			thumbnail_row = thumbnail_index / self._num_columns
			
			x = thumbnail_col * thumbnail_span_width + CC.THUMBNAIL_MARGIN
			
			y = ( thumbnail_row - ( page_index * self._num_rows_per_canvas_page ) ) * thumbnail_span_height + CC.THUMBNAIL_MARGIN
			
			dc = wx.MemoryDC( canvas_bmp )
			
			dc.DrawBitmap( thumbnail.GetBmp(), x, y )
			
		
	
	def _ExportFiles( self ):
		
		if len( self._selected_media ) > 0:
			
			try:
				
				flat_media = []
				
				for media in self._sorted_media:
					
					if media in self._selected_media:
						
						if media.IsCollection(): flat_media.extend( media.GetFlatMedia() )
						else: flat_media.append( media )
						
					
				
				with ClientGUIDialogs.DialogSetupExport( None, flat_media ) as dlg: dlg.ShowModal()
				
				self.SetFocus()
				
			except: wx.MessageBox( traceback.format_exc() )
			
		
	
	def _ExportTags( self ):
		
		if len( self._selected_media ) > 0:
			
			try:
				
				flat_media = []
				
				for media in self._sorted_media:
					
					if media in self._selected_media:
						
						if media.IsCollection(): flat_media.extend( media.GetFlatMedia() )
						else: flat_media.append( media )
						
					
				
				services = HC.app.GetManager( 'services' ).GetServices( ( HC.LOCAL_TAG, HC.TAG_REPOSITORY, HC.COMBINED_TAG ) )
				
				service_keys = [ service.GetServiceKey() for service in services ]
				
				service_key = ClientGUIDialogs.SelectServiceKey( service_keys = service_keys )
				
				if service_key is not None:
					
					with wx.FileDialog( self, style = wx.FD_SAVE, defaultFile = 'tag_update.yaml' ) as dlg:
						
						if dlg.ShowModal() == wx.ID_OK:
							
							hash_ids_to_hashes = dict( enumerate( ( m.GetHash() for m in flat_media ) ) )
							hashes_to_hash_ids = { hash : hash_id for ( hash_id, hash ) in hash_ids_to_hashes.items() }
							
							tags_to_hash_ids = collections.defaultdict( list )
							
							for m in flat_media:
								
								hash = m.GetHash()
								hash_id = hashes_to_hash_ids[ hash ]
								
								tags_manager = m.GetTagsManager()
								
								current_tags = tags_manager.GetCurrent()
								
								for tag in current_tags: tags_to_hash_ids[ tag ].append( hash_id )
								
							
							#
							
							service_data = {}
							content_data = HC.GetEmptyDataDict()
							
							mappings = tags_to_hash_ids.items()
							
							content_data[ HC.CONTENT_DATA_TYPE_MAPPINGS ][ HC.CONTENT_UPDATE_ADD ] = mappings
							
							update = HC.ServerToClientUpdate( service_data, content_data, hash_ids_to_hashes )
							
							yaml_text = yaml.safe_dump( update )
							
							with open( dlg.GetPath(), 'wb' ) as f: f.write( yaml_text )
							
						
					
				
				self.SetFocus()
				
			except: wx.MessageBox( traceback.format_exc() )
			
		
	
	def _FadeThumbnail( self, thumbnail_index ):
		
		thumbnail = self._sorted_media[ thumbnail_index ]
		
		hash = thumbnail.GetDisplayMedia().GetHash()
		
		self._StopFading( hash )
		
		bmp = thumbnail.GetBmp()
		
		image = bmp.ConvertToImage()
		
		try: image.InitAlpha()
		except: pass
		
		image = image.AdjustChannels( 1, 1, 1, 0.25 )
		
		alpha_bmp = wx.BitmapFromImage( image, 32 )
		
		wx.CallAfter( image.Destroy )
		
		self._thumbnails_being_faded_in[ hash ] = ( bmp, alpha_bmp, thumbnail_index, thumbnail, 0 )
		
		if not self._timer_animation.IsRunning(): self._timer_animation.Start( 1, wx.TIMER_ONE_SHOT )
		
	
	def _GenerateMediaCollection( self, media_results ): return ThumbnailMediaCollection( self._file_service_key, media_results )
	
	def _GenerateMediaSingleton( self, media_result ): return ThumbnailMediaSingleton( self._file_service_key, media_result )
	
	def _GetMediaCoordinates( self, media ):
		
		try: index = self._sorted_media.index( media )
		except: return ( -1, -1 )
		
		row = index / self._num_columns
		column = index % self._num_columns
		
		( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
		
		( x, y ) = ( column * thumbnail_span_width + CC.THUMBNAIL_MARGIN, row * thumbnail_span_height + CC.THUMBNAIL_MARGIN )
		
		return ( x, y )
		
	
	def _GetPageIndexFromThumbnailIndex( self, thumbnail_index ):
		
		thumbnails_per_page = self._num_columns * self._num_rows_per_canvas_page
		
		page_index = thumbnail_index / thumbnails_per_page
		
		return page_index
		
	
	def _GetThumbnailUnderMouse( self, mouse_event ):
		
		( xUnit, yUnit ) = self.GetScrollPixelsPerUnit()
		
		( x_scroll, y_scroll ) = self.GetViewStart()
		
		y_offset = y_scroll * yUnit
		
		x = mouse_event.GetX()
		y = mouse_event.GetY() + y_offset
		
		( t_span_x, t_span_y ) = self._thumbnail_span_dimensions
		
		x_mod = x % t_span_x
		y_mod = y % t_span_y
		
		if x_mod <= CC.THUMBNAIL_MARGIN or y_mod <= CC.THUMBNAIL_MARGIN or x_mod > t_span_x - CC.THUMBNAIL_MARGIN or y_mod > t_span_y - CC.THUMBNAIL_MARGIN: return None
		
		column_index = ( x / t_span_x )
		row_index = ( y / t_span_y )
		
		if column_index >= self._num_columns: return None
		
		thumbnail_index = self._num_columns * row_index + column_index
		
		if thumbnail_index >= len( self._sorted_media ): return None
		
		return self._sorted_media[ thumbnail_index ]
		
	
	def _GetYStart( self ):
		
		( my_virtual_width, my_virtual_height ) = self.GetVirtualSize()
		
		( my_width, my_height ) = self.GetClientSize()
		
		( xUnit, yUnit ) = self.GetScrollPixelsPerUnit()
		
		max_y = ( my_virtual_height - my_height ) / yUnit
		
		if ( my_virtual_height - my_height ) % yUnit > 0: max_y += 1
		
		( x, y ) = self.GetViewStart()
		
		y = max( 0, y )
		
		y = min( y, max_y )
		
		return y
		
	
	def _MoveFocussedThumbnail( self, rows, columns, shift ):
		
		if self._focussed_media is not None:
			
			current_position = self._sorted_media.index( self._focussed_media )
			
			new_position = current_position + columns + ( self._num_columns * rows )
			
			if new_position < 0: new_position = 0
			elif new_position > len( self._sorted_media ) - 1: new_position = len( self._sorted_media ) - 1
			
			self._HitMedia( self._sorted_media[ new_position ], False, shift )
			
			self._ScrollToMedia( self._focussed_media )
			
		
	
	def _RecalculateVirtualSize( self ):
		
		( client_width, client_height ) = self.GetClientSize()
		
		if client_width > 0 and client_height > 0:
			
			( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
			
			num_media = len( self._sorted_media )
			
			num_rows = max( 1, num_media / self._num_columns )
			
			if num_media % self._num_columns > 0: num_rows += 1
			
			virtual_width = client_width
			
			virtual_height = max( num_rows * thumbnail_span_height, client_height )
			
			if ( virtual_width, virtual_height ) != self.GetVirtualSize(): self.SetVirtualSize( ( virtual_width, virtual_height ) )
			
		
	
	def _RedrawMediaIfLoaded( self, thumbnails ):
		
		loaded_thumbnails = [ thumbnail for thumbnail in thumbnails if thumbnail.IsLoaded() ]
		
		indices = [ self._sorted_media.index( thumbnail ) for thumbnail in loaded_thumbnails ]
		
		indices_to_draw = [ index for index in indices if self._ThumbnailIndexIsClean( index ) ]
		
		for index in indices_to_draw:
			
			self._FadeThumbnail( index )
			
		
		self.Refresh()
		
	
	def _ReinitialisePageCacheIfNeeded( self ):
		
		old_num_rows = self._num_rows_per_canvas_page
		old_num_columns = self._num_columns
		
		( old_client_width, old_client_height ) = self._last_client_size
		
		( client_width, client_height ) = self.GetClientSize()
		
		( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
		
		num_rows = client_height / thumbnail_span_height
		
		if client_height % thumbnail_span_height > 0: num_rows += 1
		
		self._num_rows_per_canvas_page = max( 1, num_rows )
		
		self._num_columns = max( 1, client_width / thumbnail_span_width )
		
		thumb_dimensions_changed = old_num_columns != self._num_columns or old_num_rows != self._num_rows_per_canvas_page
		
		width_got_bigger = old_client_width < client_width
		
		if thumb_dimensions_changed or width_got_bigger:
			
			self._client_bmp = wx.EmptyBitmap( client_width, client_height, 24 )
			
			for ( index, bmp ) in self._clean_canvas_pages.items(): wx.CallAfter( bmp.Destroy )
			
			for bmp in self._dirty_canvas_pages: wx.CallAfter( bmp.Destroy )
			
			self._clean_canvas_pages = {}
			self._dirty_canvas_pages = []
			
			for i in range( 5 ): self._dirty_canvas_pages.append( wx.EmptyBitmap( client_width, self._num_rows_per_canvas_page * thumbnail_span_width, 24 ) )
			
		
	
	def _Remove( self ):
		
		singletons = [ media for media in self._selected_media if not media.IsCollection() ]
		
		collections = [ media for media in self._selected_media if media.IsCollection() ]
		
		self._RemoveMedia( singletons, collections )
		
	
	def _RemoveMedia( self, singleton_media, collected_media ):
		
		MediaPanel._RemoveMedia( self, singleton_media, collected_media )
		
		self._selected_media.difference_update( singleton_media )
		self._selected_media.difference_update( collected_media )
		
		if self._focussed_media not in self._selected_media: self._SetFocussedMedia( None )
		
		self._shift_focussed_media = None
		
		self._RecalculateVirtualSize()
		
		self._DirtyAllPages()
		
		self._PublishSelectionChange()
		
		HC.pubsub.pub( 'sorted_media_pulse', self._page_key, self._sorted_media )
		
	
	def _ScrollEnd( self, shift = False ):
		
		if len( self._sorted_media ) > 0:
			
			end_media = self._sorted_media[ -1 ]
			
			self._HitMedia( end_media, False, shift )
			
			self._ScrollToMedia( end_media )
			
		
	
	def _ScrollHome( self, shift = False ):
		
		if len( self._sorted_media ) > 0:
			
			home_media = self._sorted_media[ 0 ]
			
			self._HitMedia( home_media, False, shift )
			
			self._ScrollToMedia( home_media )
			
		
	
	def _ScrollToMedia( self, media ):
		
		if media is not None:
			
			( x, y ) = self._GetMediaCoordinates( media )
			
			( start_x, start_y ) = self.GetViewStart()
			
			( x_unit, y_unit ) = self.GetScrollPixelsPerUnit()
			
			( width, height ) = self.GetClientSize()
			
			( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
			
			if y < start_y * y_unit:
				
				y_to_scroll_to = y / y_unit
				
				self.Scroll( -1, y_to_scroll_to )
				
				wx.PostEvent( self, wx.ScrollWinEvent( wx.wxEVT_SCROLLWIN_THUMBRELEASE, pos = y_to_scroll_to ) )
				
			elif y > ( start_y * y_unit ) + height - thumbnail_span_height:
				
				y_to_scroll_to = ( y - height ) / y_unit
				
				self.Scroll( -1, y_to_scroll_to + 2 )
				
				wx.PostEvent( self, wx.ScrollWinEvent( wx.wxEVT_SCROLLWIN_THUMBRELEASE, pos = y_to_scroll_to + 2 ) )
				
			
		
	
	def _StopFading( self, hash ):
		
		if hash in self._thumbnails_being_faded_in:
			
			( bmp, alpha_bmp, thumbnail_index, thumbnail, num_frames ) = self._thumbnails_being_faded_in[ hash ]
			
			wx.CallAfter( bmp.Destroy )
			wx.CallAfter( alpha_bmp.Destroy )
			
			del self._thumbnails_being_faded_in[ hash ]
			
		
	
	def _ThumbnailIndexIsClean( self, thumbnail_index ):
		
		page_index = self._GetPageIndexFromThumbnailIndex( thumbnail_index )
		
		return page_index in self._clean_canvas_pages
		
	
	def AddMediaResults( self, page_key, media_results, append = True ):
		
		if page_key == self._page_key:
			
			thumbnails = MediaPanel.AddMediaResults( self, page_key, media_results, append = append )
			
			self._RecalculateVirtualSize()
			
			for thumbnail in thumbnails:
				
				thumbnail_index = self._sorted_media.index( thumbnail )
				
				self._FadeThumbnail( thumbnail_index )
				
			
			self._PublishSelectionChange()
			
		
	
	def EventEraseBackground( self, event ): pass
	
	def EventKeyDown( self, event ):
		
		# accelerator tables can't handle escape key in windows, gg
		
		if event.GetKeyCode() == wx.WXK_ESCAPE: self._Select( 'none' )
		else: event.Skip()
		
	
	def EventMenu( self, event ):
		
		action = CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetAction( event.GetId() )
		
		if action is not None:
			
			( command, data ) = action
			
			if command == 'archive': self._Archive()
			elif command == 'copy_bmp': self._CopyBMPToClipboard()
			elif command == 'copy_files':
				with wx.BusyCursor(): HC.app.Write( 'copy_files', self._GetSelectedHashes( CC.DISCRIMINANT_LOCAL ) )
			elif command == 'copy_hash': self._CopyHashToClipboard()
			elif command == 'copy_hashes': self._CopyHashesToClipboard()
			elif command == 'copy_local_url': self._CopyLocalUrlToClipboard()
			elif command == 'copy_path': self._CopyPathToClipboard()
			elif command == 'ctrl-space':
				
				if self._focussed_media is not None: self._HitMedia( self._focussed_media, True, False )
				
			elif command == 'custom_filter': self._CustomFilter()
			elif command == 'delete': self._Delete( data )
			elif command == 'download': HC.app.Write( 'content_updates', { HC.LOCAL_FILE_SERVICE_KEY : [ HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_PENDING, self._GetSelectedHashes( CC.DISCRIMINANT_NOT_LOCAL ) ) ] } )
			elif command == 'export_files': self._ExportFiles()
			elif command == 'export_tags': self._ExportTags()
			elif command == 'filter': self._Filter()
			elif command == 'fullscreen': self._FullScreen()
			elif command == 'get_similar_to': self._GetSimilarTo()
			elif command == 'inbox': self._Inbox()
			elif command == 'manage_ratings': self._ManageRatings()
			elif command == 'manage_tags': self._ManageTags()
			elif command == 'modify_account': self._ModifyUploaders( data )
			elif command == 'new_thread_dumper': self._NewThreadDumper()
			elif command == 'open_externally': self._OpenExternally()
			elif command == 'petition': self._PetitionFiles( data )
			elif command == 'ratings_filter': self._RatingsFilter( data )
			elif command == 'remove': self._Remove()
			elif command == 'rescind_petition': self._RescindPetitionFiles( data )
			elif command == 'rescind_upload': self._RescindUploadFiles( data )
			elif command == 'scroll_end': self._ScrollEnd( False )
			elif command == 'scroll_home': self._ScrollHome( False )
			elif command == 'shift_scroll_end': self._ScrollEnd( True )
			elif command == 'shift_scroll_home': self._ScrollHome( True )
			elif command == 'select': self._Select( data )
			elif command == 'share_on_local_booru': self._ShareOnLocalBooru()
			elif command == 'show_selection_in_new_query_page': self._ShowSelectionInNewQueryPage()
			elif command == 'upload': self._UploadFiles( data )
			elif command == 'key_up': self._MoveFocussedThumbnail( -1, 0, False )
			elif command == 'key_down': self._MoveFocussedThumbnail( 1, 0, False )
			elif command == 'key_left': self._MoveFocussedThumbnail( 0, -1, False )
			elif command == 'key_right': self._MoveFocussedThumbnail( 0, 1, False )
			elif command == 'key_shift_up': self._MoveFocussedThumbnail( -1, 0, True )
			elif command == 'key_shift_down': self._MoveFocussedThumbnail( 1, 0, True )
			elif command == 'key_shift_left': self._MoveFocussedThumbnail( 0, -1, True )
			elif command == 'key_shift_right': self._MoveFocussedThumbnail( 0, 1, True )
			else: event.Skip()
			
		
	
	def EventMouseFullScreen( self, event ):
		
		t = self._GetThumbnailUnderMouse( event )
		
		if t is not None:
			
			locations_manager = t.GetLocationsManager()
			
			if locations_manager.HasLocal(): self._FullScreen( t )
			elif self._file_service_key != HC.COMBINED_FILE_SERVICE_KEY:
				
				if len( locations_manager.GetCurrentRemote() ) > 0:
					
					HC.app.Write( 'content_updates', { HC.LOCAL_FILE_SERVICE_KEY : [ HC.ContentUpdate( HC.CONTENT_DATA_TYPE_FILES, HC.CONTENT_UPDATE_PENDING, t.GetHashes() ) ] } )
					
				
			
		
	
	def EventPaint( self, event ):
		
		page_indices_to_display = self._CalculateVisiblePageIndices()
		
		dc = wx.BufferedPaintDC( self, self._client_bmp )
		
		( xUnit, yUnit ) = self.GetScrollPixelsPerUnit()
		
		y_start = self._GetYStart()
		
		earliest_y = y_start * yUnit
		
		earliest_page_index_to_display = min( page_indices_to_display )
		last_page_index_to_display = max( page_indices_to_display )
		
		page_indices_to_draw = list( page_indices_to_display )
		
		if earliest_page_index_to_display > 0: page_indices_to_draw.insert( 0, earliest_page_index_to_display - 1 )
		page_indices_to_draw.append( last_page_index_to_display + 1 )
		
		potential_clean_indices_to_steal = [ page_index for page_index in self._clean_canvas_pages.keys() if page_index not in page_indices_to_draw ]
		
		potential_clean_indices_to_steal.sort( reverse = True )
		
		for page_index in page_indices_to_draw:
			
			if page_index not in self._clean_canvas_pages:
				
				if len( self._dirty_canvas_pages ) > 0: bmp = self._dirty_canvas_pages.pop()
				else:
					
					index_to_steal = potential_clean_indices_to_steal.pop()
					
					bmp = self._clean_canvas_pages[ index_to_steal ]
					
					del self._clean_canvas_pages[ index_to_steal ]
					
				
				self._DrawCanvasPage( page_index, bmp )
				
				self._clean_canvas_pages[ page_index ] = bmp
				
			
			if page_index in page_indices_to_draw:
				
				bmp = self._clean_canvas_pages[ page_index ]
				
				( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
				
				page_y_start = thumbnail_span_height * self._num_rows_per_canvas_page * page_index
				
				dc.DrawBitmap( bmp, 0, page_y_start - earliest_y )
				
			
		
	
	def EventResize( self, event ):
		
		self._ReinitialisePageCacheIfNeeded()
		
		self._RecalculateVirtualSize()
		
		self.Refresh() # in case of small resizes where a dc isn't created, I think, where we get tiny black lines
		
		self._last_client_size = self.GetClientSize()
		
	
	def EventSelection( self, event ):
		
		self._HitMedia( self._GetThumbnailUnderMouse( event ), event.CmdDown(), event.ShiftDown() )
		
		if not ( event.CmdDown() or event.ShiftDown() ): self._ScrollToMedia( self._focussed_media )
		
		event.Skip()
		
	
	def EventShowMenu( self, event ):
		
		thumbnail = self._GetThumbnailUnderMouse( event )
		
		if thumbnail is not None: self._HitMedia( thumbnail, event.CmdDown(), event.ShiftDown() )
		
		all_locations_managers = [ media.GetLocationsManager() for media in self._selected_media ]
		
		selection_has_local = True in ( locations_manager.HasLocal() for locations_manager in all_locations_managers )
		selection_has_inbox = True in ( media.HasInbox() for media in self._selected_media )
		selection_has_archive = True in ( media.HasArchive() for media in self._selected_media )
		
		media_has_inbox = True in ( media.HasInbox() for media in self._sorted_media )
		media_has_archive = True in ( media.HasArchive() for media in self._sorted_media )
		
		menu = wx.Menu()
		
		if thumbnail is None:
			
			if self._refreshable:
				
				menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'refresh' ), 'refresh' )
				
			
			if len( self._sorted_media ) > 0:
				
				if menu.GetMenuItemCount() > 0: menu.AppendSeparator()
				
				select_menu = wx.Menu()
				
				if len( self._selected_media ) < len( self._sorted_media ):
					
					select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'all' ), 'all' )
					
				
				select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'invert' ), 'invert' )
				
				if media_has_archive and media_has_inbox:
					
					select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'inbox' ), 'inbox' )
					select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'archive' ), 'archive' )
					
				
				select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'none' ), 'none' )
				
				menu.AppendMenu( CC.ID_NULL, 'select', select_menu )
				
			
		else:
			
			if self._focussed_media is not None:
				
				# variables
				
				num_selected = self._GetNumSelected()
				
				multiple_selected = num_selected > 1
				
				services = HC.app.GetManager( 'services' ).GetServices()
				
				tag_repositories = [ service for service in services if service.GetServiceType() == HC.TAG_REPOSITORY ]
				
				file_repositories = [ service for service in services if service.GetServiceType() == HC.FILE_REPOSITORY ]
				
				local_ratings_services = [ service for service in services if service.GetServiceType() in ( HC.LOCAL_RATING_LIKE, HC.LOCAL_RATING_NUMERICAL ) ]
				
				i_can_post_ratings = len( local_ratings_services ) > 0
				
				downloadable_file_service_keys = { repository.GetServiceKey() for repository in file_repositories if repository.GetInfo( 'account' ).HasPermission( HC.GET_DATA ) or repository.GetInfo( 'account' ).IsUnknownAccount() }
				uploadable_file_service_keys = { repository.GetServiceKey() for repository in file_repositories if repository.GetInfo( 'account' ).HasPermission( HC.POST_DATA ) or repository.GetInfo( 'account' ).IsUnknownAccount() }
				petition_resolvable_file_service_keys = { repository.GetServiceKey() for repository in file_repositories if repository.GetInfo( 'account' ).HasPermission( HC.RESOLVE_PETITIONS ) }
				petitionable_file_service_keys = { repository.GetServiceKey() for repository in file_repositories if repository.GetInfo( 'account' ).HasPermission( HC.POST_PETITIONS ) } - petition_resolvable_file_service_keys
				user_manageable_file_service_keys = { repository.GetServiceKey() for repository in file_repositories if repository.GetInfo( 'account' ).HasPermission( HC.MANAGE_USERS ) }
				admin_file_service_keys = { repository.GetServiceKey() for repository in file_repositories if repository.GetInfo( 'account' ).HasPermission( HC.GENERAL_ADMIN ) }
				
				if multiple_selected:
					
					uploaded_phrase = 'all uploaded to'
					pending_phrase = 'all pending to'
					petitioned_phrase = 'all petitioned from'
					deleted_phrase = 'all deleted from'
					
					download_phrase = 'download all possible'
					upload_phrase = 'upload all possible to'
					rescind_upload_phrase = 'rescind pending uploads to'
					petition_phrase = 'petition all possible for removal from'
					rescind_petition_phrase = 'rescind petitions for'
					remote_delete_phrase = 'delete all possible from'
					modify_account_phrase = 'modify the accounts that uploaded these to'
					
					manage_tags_phrase = 'files\' tags'
					manage_ratings_phrase = 'files\' ratings'
					
					archive_phrase = 'archive all'
					inbox_phrase = 'return all to inbox'
					remove_phrase = 'remove all'
					local_delete_phrase = 'delete all'
					dump_phrase = 'dump all to 4chan'
					export_phrase = 'files'
					copy_phrase = 'files'
					
				else:
					
					uploaded_phrase = 'uploaded to'
					pending_phrase = 'pending to'
					petitioned_phrase = 'petitioned from'
					deleted_phrase = 'deleted from'
					
					download_phrase = 'download'
					upload_phrase = 'upload to'
					rescind_upload_phrase = 'rescind pending upload to'
					petition_phrase = 'petition for removal from'
					rescind_petition_phrase = 'rescind petition for'
					remote_delete_phrase = 'delete from'
					modify_account_phrase = 'modify the account that uploaded this to'
					
					manage_tags_phrase = 'file\'s tags'
					manage_ratings_phrase = 'file\'s ratings'
					
					archive_phrase = 'archive'
					inbox_phrase = 'return to inbox'
					remove_phrase = 'remove'
					local_delete_phrase = 'delete'
					dump_phrase = 'dump to 4chan'
					export_phrase = 'file'
					copy_phrase = 'file'
					
				
				# info about the files
				
				def MassUnion( lists ): return { item for item in itertools.chain.from_iterable( lists ) }
				
				all_current_file_service_keys = [ locations_manager.GetCurrentRemote() for locations_manager in all_locations_managers ]
				
				current_file_service_keys = HC.IntelligentMassIntersect( all_current_file_service_keys )
				
				some_current_file_service_keys = MassUnion( all_current_file_service_keys ) - current_file_service_keys
				
				all_pending_file_service_keys = [ locations_manager.GetPendingRemote() for locations_manager in all_locations_managers ]
				
				pending_file_service_keys = HC.IntelligentMassIntersect( all_pending_file_service_keys )
				
				some_pending_file_service_keys = MassUnion( all_pending_file_service_keys ) - pending_file_service_keys
				
				selection_uploaded_file_service_keys = some_pending_file_service_keys.union( pending_file_service_keys )
				
				all_petitioned_file_service_keys = [ locations_manager.GetPetitionedRemote() for locations_manager in all_locations_managers ]
				
				petitioned_file_service_keys = HC.IntelligentMassIntersect( all_petitioned_file_service_keys )
				
				some_petitioned_file_service_keys = MassUnion( all_petitioned_file_service_keys ) - petitioned_file_service_keys
				
				selection_petitioned_file_service_keys = some_petitioned_file_service_keys.union( petitioned_file_service_keys )
				
				all_deleted_file_service_keys = [ locations_manager.GetDeletedRemote() for locations_manager in all_locations_managers ]
				
				deleted_file_service_keys = HC.IntelligentMassIntersect( all_deleted_file_service_keys )
				
				some_deleted_file_service_keys = MassUnion( all_deleted_file_service_keys ) - deleted_file_service_keys
				
				# valid commands for the files
				
				selection_uploadable_file_service_keys = set()
				
				selection_downloadable_file_service_keys = set()
				
				selection_petitionable_file_service_keys = set()
				
				for locations_manager in all_locations_managers:
					
					# we can upload (set pending) to a repo_id when we have permission, a file is local, not current, not pending, and either ( not deleted or admin )
					
					if locations_manager.HasLocal(): selection_uploadable_file_service_keys.update( uploadable_file_service_keys - locations_manager.GetCurrentRemote() - locations_manager.GetPendingRemote() - ( locations_manager.GetDeletedRemote() - admin_file_service_keys ) )
					
					# we can download (set pending to local) when we have permission, a file is not local and not already downloading and current
					
					if not locations_manager.HasLocal() and not locations_manager.HasDownloading(): selection_downloadable_file_service_keys.update( downloadable_file_service_keys & locations_manager.GetCurrentRemote() )
					
					# we can petition when we have permission and a file is current
					# we can re-petition an already petitioned file
					
					selection_petitionable_file_service_keys.update( petitionable_file_service_keys & locations_manager.GetCurrentRemote() )
					
				
				selection_deletable_file_service_keys = set()
				
				for locations_manager in all_locations_managers:
					
					# we can delete remote when we have permission and a file is current and it is not already petitioned
					
					selection_deletable_file_service_keys.update( ( petition_resolvable_file_service_keys & locations_manager.GetCurrentRemote() ) - locations_manager.GetPetitionedRemote() )
					
				
				selection_modifyable_file_service_keys = set()
				
				for locations_manager in all_locations_managers:
					
					# we can modify users when we have permission and the file is current or deleted
					
					selection_modifyable_file_service_keys.update( user_manageable_file_service_keys & ( locations_manager.GetCurrentRemote() | locations_manager.GetDeletedRemote() ) )
					
				
				# do the actual menu
				
				if multiple_selected: menu.Append( CC.ID_NULL, HC.ConvertIntToPrettyString( num_selected ) + ' files, ' + self._GetPrettyTotalSelectedSize() )
				else:
					
					menu.Append( CC.ID_NULL, thumbnail.GetPrettyInfo() )
					menu.Append( CC.ID_NULL, thumbnail.GetPrettyAge() )
					
				
				if len( some_current_file_service_keys ) > 0: AddFileServiceKeysToMenu( menu, some_current_file_service_keys, 'some uploaded to', CC.ID_NULL )
				
				if len( current_file_service_keys ) > 0: AddFileServiceKeysToMenu( menu, current_file_service_keys, uploaded_phrase, CC.ID_NULL )
				
				if len( some_pending_file_service_keys ) > 0: AddFileServiceKeysToMenu( menu, some_pending_file_service_keys, 'some pending to', CC.ID_NULL )
				
				if len( pending_file_service_keys ) > 0: AddFileServiceKeysToMenu( menu, pending_file_service_keys, pending_phrase, CC.ID_NULL )
				
				if len( some_petitioned_file_service_keys ) > 0: AddFileServiceKeysToMenu( menu, some_petitioned_file_service_keys, 'some petitioned from', CC.ID_NULL )
				
				if len( petitioned_file_service_keys ) > 0: AddFileServiceKeysToMenu( menu, petitioned_file_service_keys, petitioned_phrase, CC.ID_NULL )
				
				if len( some_deleted_file_service_keys ) > 0: AddFileServiceKeysToMenu( menu, some_deleted_file_service_keys, 'some deleted from', CC.ID_NULL )
				
				if len( deleted_file_service_keys ) > 0: AddFileServiceKeysToMenu( menu, deleted_file_service_keys, deleted_phrase, CC.ID_NULL )
				
				menu.AppendSeparator()
				
				#
				
				len_interesting_file_service_keys = 0
				
				len_interesting_file_service_keys += len( selection_downloadable_file_service_keys )
				len_interesting_file_service_keys += len( selection_uploadable_file_service_keys )
				len_interesting_file_service_keys += len( selection_uploaded_file_service_keys )
				len_interesting_file_service_keys += len( selection_petitionable_file_service_keys )
				len_interesting_file_service_keys += len( selection_petitioned_file_service_keys )
				len_interesting_file_service_keys += len( selection_deletable_file_service_keys )
				len_interesting_file_service_keys += len( selection_modifyable_file_service_keys )
				
				if len_interesting_file_service_keys > 0:
					
					file_repo_menu = wx.Menu()
					
					if len( selection_downloadable_file_service_keys ) > 0: file_repo_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'download' ), download_phrase )
					
					if len( selection_uploadable_file_service_keys ) > 0: AddFileServiceKeysToMenu( file_repo_menu, selection_uploadable_file_service_keys, upload_phrase, 'upload' )
					
					if len( selection_uploaded_file_service_keys ) > 0: AddFileServiceKeysToMenu( file_repo_menu, selection_uploaded_file_service_keys, rescind_upload_phrase, 'rescind_upload' )
					
					if len( selection_petitionable_file_service_keys ) > 0: AddFileServiceKeysToMenu( file_repo_menu, selection_petitionable_file_service_keys, petition_phrase, 'petition' )
					
					if len( selection_petitioned_file_service_keys ) > 0: AddFileServiceKeysToMenu( file_repo_menu, selection_petitioned_file_service_keys, rescind_petition_phrase, 'rescind_petition' )
					
					if len( selection_deletable_file_service_keys ) > 0: AddFileServiceKeysToMenu( file_repo_menu, selection_deletable_file_service_keys, remote_delete_phrase, 'delete' )
					
					if len( selection_modifyable_file_service_keys ) > 0: AddFileServiceKeysToMenu( file_repo_menu, selection_modifyable_file_service_keys, modify_account_phrase, 'modify_account' )
					
					menu.AppendMenu( CC.ID_NULL, 'file repositories', file_repo_menu )
					
				
				#
				
				manage_menu = wx.Menu()
				
				manage_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'manage_tags' ), manage_tags_phrase )
				
				if i_can_post_ratings: manage_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'manage_ratings' ), manage_ratings_phrase )
				
				menu.AppendMenu( CC.ID_NULL, 'manage', manage_menu )
				
				#
				
				if selection_has_local:
					
					if multiple_selected or i_can_post_ratings: 
						
						filter_menu = wx.Menu()
						
						if multiple_selected: filter_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'filter' ), 'archive/delete' )
						
						if i_can_post_ratings:
							
							ratings_filter_menu = wx.Menu()
							
							for service in local_ratings_services: ratings_filter_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'ratings_filter', service.GetServiceKey() ), service.GetName() )
							
							filter_menu.AppendMenu( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'ratings_filter' ), 'ratings filter', ratings_filter_menu )
							
						
						if multiple_selected: filter_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'custom_filter' ), 'custom filter' )
						
						menu.AppendMenu( CC.ID_NULL, 'filter', filter_menu )
						
					
				
				menu.AppendSeparator()
				
				if selection_has_local:
					
					if selection_has_inbox: menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'archive' ), archive_phrase )
					if selection_has_archive: menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'inbox' ), inbox_phrase )
					
					menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'remove' ), remove_phrase )
					menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'delete', HC.LOCAL_FILE_SERVICE_KEY ), local_delete_phrase )
					
				
				# share
				
				menu.AppendSeparator()
				
				menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'open_externally', HC.LOCAL_FILE_SERVICE_KEY ), '&open externally' )
				
				share_menu = wx.Menu()
				
				#
				
				copy_menu = wx.Menu()
				
				copy_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'copy_files' ), copy_phrase )
				copy_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'copy_hash' ) , 'hash' )
				if multiple_selected: copy_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'copy_hashes' ) , 'hashes' )
				if self._focussed_media.GetMime() in HC.IMAGES and self._focussed_media.GetDuration() is None: copy_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'copy_bmp' ) , 'image' )
				copy_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'copy_path' ) , 'path' )
				copy_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'copy_local_url' ) , 'local url' )
				
				share_menu.AppendMenu( CC.ID_NULL, 'copy', copy_menu )
				
				#
				
				share_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'new_thread_dumper' ), dump_phrase )
				
				#
				
				export_menu  = wx.Menu()
				
				export_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'export_files' ), export_phrase )
				export_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'export_tags' ), 'tags' )
				
				share_menu.AppendMenu( CC.ID_NULL, 'export', export_menu )
				
				#
				
				share_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'share_on_local_booru' ), 'on local booru' )
				
				#
				
				menu.AppendMenu( CC.ID_NULL, 'share', share_menu )
				
				#
				
				if self._refreshable:
					
					menu.AppendSeparator()
					
					menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'refresh' ), 'refresh' )
					
				
				if len( self._sorted_media ) > 0:
					
					menu.AppendSeparator()
					
					select_menu = wx.Menu()
					
					select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'all' ), 'all' )
					
					select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'invert' ), 'invert' )
					
					if media_has_archive and media_has_inbox:
						
						select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'inbox' ), 'inbox' )
						select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'archive' ), 'archive' )
						
					
					select_menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'none' ), 'none' )
					
					menu.AppendMenu( CC.ID_NULL, 'select', select_menu )
					
				
				menu.AppendSeparator()
				
				menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'show_selection_in_new_query_page' ), 'open selection in a new page' )
				
				if self._focussed_media.HasImages():
					
					menu.AppendSeparator()
					
					menu.Append( CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'get_similar_to' ) , 'find very similar images' )
					
				
			
		
		if menu.GetMenuItemCount() > 0: self.PopupMenu( menu )
		
		wx.CallAfter( menu.Destroy )
		
		event.Skip()
		
	
	def NewThumbnails( self, hashes ):
		
		affected_thumbnails = self._GetMedia( hashes )
		
		if len( affected_thumbnails ) > 0:
			
			for t in affected_thumbnails: t.ReloadFromDB()
			
			self._RedrawMediaIfLoaded( affected_thumbnails )
			
		
	
	def RefreshAcceleratorTable( self ):
		
		entries = [
		( wx.ACCEL_NORMAL, wx.WXK_HOME, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'scroll_home' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_NUMPAD_HOME, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'scroll_home' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_END, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'scroll_end' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_NUMPAD_END, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'scroll_end' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_DELETE, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'delete', HC.LOCAL_FILE_SERVICE_KEY ) ),
		( wx.ACCEL_NORMAL, wx.WXK_NUMPAD_DELETE, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'delete', HC.LOCAL_FILE_SERVICE_KEY ) ),
		( wx.ACCEL_NORMAL, wx.WXK_RETURN, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'fullscreen' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_NUMPAD_ENTER, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'fullscreen' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_UP, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_up' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_NUMPAD_UP, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_up' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_DOWN, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_down' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_NUMPAD_DOWN, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_down' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_LEFT, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_left' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_NUMPAD_LEFT, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_left' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_RIGHT, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_right' ) ),
		( wx.ACCEL_NORMAL, wx.WXK_NUMPAD_RIGHT, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_right' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_HOME, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'shift_scroll_home' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_NUMPAD_HOME, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'shift_scroll_home' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_END, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'shift_scroll_end' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_NUMPAD_END, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'shift_scroll_end' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_UP, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_shift_up' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_NUMPAD_UP, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_shift_up' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_DOWN, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_shift_down' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_NUMPAD_DOWN, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_shift_down' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_LEFT, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_shift_left' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_NUMPAD_LEFT, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_shift_left' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_RIGHT, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_shift_right' ) ),
		( wx.ACCEL_SHIFT, wx.WXK_NUMPAD_RIGHT, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'key_shift_right' ) ),
		( wx.ACCEL_CTRL, ord( 'A' ), CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'select', 'all' ) ),
		( wx.ACCEL_CTRL, ord( 'c' ), CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'copy_files' )  ),
		( wx.ACCEL_CTRL, wx.WXK_SPACE, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( 'ctrl-space' )  )
		]
		
		for ( modifier, key_dict ) in HC.options[ 'shortcuts' ].items(): entries.extend( [ ( modifier, key, CC.MENU_EVENT_ID_TO_ACTION_CACHE.GetId( action ) ) for ( key, action ) in key_dict.items() ] )
		
		self.SetAcceleratorTable( wx.AcceleratorTable( entries ) )
		
	
	def SetFocussedMedia( self, page_key, media ):
		
		MediaPanel.SetFocussedMedia( self, page_key, media )
		
		if page_key == self._page_key:
			
			if media is None: self._SetFocussedMedia( None )
			else:
				
				try:
					
					my_media = self._GetMedia( media.GetHashes() )[0]
					
					self._HitMedia( my_media, False, False )
					
					self._ScrollToMedia( self._focussed_media )
					
				except: pass
				
			
		
	
	def Sort( self, page_key, sort_by = None ):
		
		MediaPanel.Sort( self, page_key, sort_by )
		
		for thumbnail in self._collected_media: thumbnail.ReloadFromDB()
		
		self._DirtyAllPages()
		
	
	def ThumbnailsResized( self ):
		
		self._thumbnail_span_dimensions = CC.AddPaddingToDimensions( HC.options[ 'thumbnail_dimensions' ], ( CC.THUMBNAIL_BORDER + CC.THUMBNAIL_MARGIN ) * 2 )
		
		( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
		
		self._ReinitialisePageCacheIfNeeded()
		
		self.SetScrollRate( 0, thumbnail_span_height )
		
		for t in self._sorted_media: t.ReloadFromDBLater()
		
		self._DirtyAllPages()
		
	
	def TIMEREventAnimation( self, event ):
		
		started = HC.GetNowPrecise()
		
		( thumbnail_span_width, thumbnail_span_height ) = self._thumbnail_span_dimensions
		
		all_info = self._thumbnails_being_faded_in.items()
		
		random.shuffle( all_info )
		
		dcs = {}
		
		for ( hash, ( original_bmp, alpha_bmp, thumbnail_index, thumbnail, num_frames_rendered ) ) in all_info:
			
			num_frames_rendered += 1
			
			page_index = self._GetPageIndexFromThumbnailIndex( thumbnail_index )
			
			delete_entry = False
			
			try: expected_thumbnail = self._sorted_media[ thumbnail_index ]
			except: expected_thumbnail = None
			
			if expected_thumbnail != thumbnail: delete_entry = True
			elif page_index not in self._clean_canvas_pages: delete_entry = True
			else:
				
				if num_frames_rendered >= 9:
					
					bmp_to_use = original_bmp
					
					delete_entry = True
					
				else:
					
					bmp_to_use = alpha_bmp
					
					self._thumbnails_being_faded_in[ hash ] = ( original_bmp, alpha_bmp, thumbnail_index, thumbnail, num_frames_rendered )
					
				
				thumbnail_col = thumbnail_index % self._num_columns
				
				thumbnail_row = thumbnail_index / self._num_columns
				
				x = thumbnail_col * thumbnail_span_width + CC.THUMBNAIL_MARGIN
				
				y = ( thumbnail_row - ( page_index * self._num_rows_per_canvas_page ) ) * thumbnail_span_height + CC.THUMBNAIL_MARGIN
				
				if page_index not in dcs:
					
					canvas_bmp = self._clean_canvas_pages[ page_index ]
					
					dc = wx.MemoryDC( canvas_bmp )
					
					dcs[ page_index ] = dc
					
				
				dc = dcs[ page_index ]
				
				dc.DrawBitmap( bmp_to_use, x, y, True )
				
			
			if delete_entry:
				
				del self._thumbnails_being_faded_in[ hash ]
				
				wx.CallAfter( original_bmp.Destroy )
				wx.CallAfter( alpha_bmp.Destroy )
				
			
			if HC.GetNowPrecise() - started > 0.016: break
			
		
		finished = HC.GetNowPrecise()
		
		if len( self._thumbnails_being_faded_in ) > 0:
			
			time_this_took_in_ms = ( finished - started ) * 1000
			
			ms = max( 1, int( round( 16.7 - time_this_took_in_ms ) ) )
			
			self._timer_animation.Start( ms, wx.TIMER_ONE_SHOT )
			
		
		self.Refresh()
		
	
	def WaterfallThumbnail( self, page_key, thumbnail, thumbnail_bmp ):
		
		if self._page_key == page_key:
			
			thumbnail.SetBmp( thumbnail_bmp )
			
			thumbnail_index = self._sorted_media.index( thumbnail )
			
			self._FadeThumbnail( thumbnail_index )
			
		
	
class Selectable( object ):
	
	def __init__( self ): self._selected = False
	
	def Deselect( self ): self._selected = False
	
	def IsLoaded( self ): return False
	
	def IsSelected( self ): return self._selected
	
	def Select( self ): self._selected = True
	
class Thumbnail( Selectable ):
	
	def __init__( self, file_service_key ):
		
		Selectable.__init__( self )
		
		self._dump_status = CC.DUMPER_NOT_DUMPED
		self._hydrus_bmp = None
		self._file_service_key = file_service_key
		
		self._my_dimensions = CC.AddPaddingToDimensions( HC.options[ 'thumbnail_dimensions' ], CC.THUMBNAIL_BORDER * 2 )
		
	
	def _LoadFromDB( self ): self._hydrus_bmp = HC.app.GetThumbnailCache().GetThumbnail( self )
	
	def Dumped( self, dump_status ): self._dump_status = dump_status
	
	def GetBmp( self ):
		
		inbox = self.HasInbox()
		
		local = self.GetLocationsManager().HasLocal()
		
		namespaces = self.GetTagsManager().GetCombinedNamespaces( ( 'creator', 'series', 'title', 'volume', 'chapter', 'page' ) )
		
		creators = namespaces[ 'creator' ]
		series = namespaces[ 'series' ]
		titles = namespaces[ 'title' ]
		volumes = namespaces[ 'volume' ]
		chapters = namespaces[ 'chapter' ]
		pages = namespaces[ 'page' ]
		
		if self._hydrus_bmp is None: self._LoadFromDB()
		
		( width, height ) = self._my_dimensions
		
		bmp = wx.EmptyBitmap( width, height, 24 )
		
		dc = wx.MemoryDC( bmp )
		
		if not local:
			
			if self._selected: rgb = HC.options[ 'gui_colours' ][ 'thumb_background_remote_selected' ]
			else: rgb = HC.options[ 'gui_colours' ][ 'thumb_background_remote' ]
			
		else:
			
			if self._selected: rgb = HC.options[ 'gui_colours' ][ 'thumb_background_selected' ]
			else: rgb = HC.options[ 'gui_colours' ][ 'thumb_background' ]
			
		
		dc.SetBackground( wx.Brush( wx.Colour( *rgb ) ) )
		
		dc.Clear()
		
		( thumb_width, thumb_height ) = self._hydrus_bmp.GetSize()
		
		x_offset = ( width - thumb_width ) / 2
		
		y_offset = ( height - thumb_height ) / 2
		
		wx_bmp = self._hydrus_bmp.GetWxBitmap()
		
		dc.DrawBitmap( wx_bmp, x_offset, y_offset )
		
		wx.CallAfter( wx_bmp.Destroy )
		
		collections_string = ''
		
		if len( volumes ) > 0:
			
			if len( volumes ) == 1:
				
				( volume, ) = volumes
				
				collections_string = 'v' + HC.u( volume )
				
			else:
				
				volumes_sorted = HydrusTags.SortTags( volumes )
				
				collections_string_append = 'v' + HC.u( volumes_sorted[0] ) + '-' + HC.u( volumes_sorted[-1] )
				
			
		
		if len( chapters ) > 0:
			
			if len( chapters ) == 1:
				
				( chapter, ) = chapters
				
				collections_string_append = 'c' + HC.u( chapter )
				
			else:
				
				chapters_sorted = HydrusTags.SortTags( chapters )
				
				collections_string_append = 'c' + HC.u( chapters_sorted[0] ) + '-' + HC.u( chapters_sorted[-1] )
				
			
			if len( collections_string ) > 0: collections_string += '-' + collections_string_append
			else: collections_string = collections_string_append
			
		
		if len( pages ) > 0:
			
			if len( pages ) == 1:
				
				( page, ) = pages
				
				collections_string_append = 'p' + HC.u( page )
				
			else:
				
				pages_sorted = HydrusTags.SortTags( pages )
				
				collections_string_append = 'p' + HC.u( pages_sorted[0] ) + '-' + HC.u( pages_sorted[-1] )
				
			
			if len( collections_string ) > 0: collections_string += '-' + collections_string_append
			else: collections_string = collections_string_append
			
		
		if len( collections_string ) > 0:
			
			dc.SetFont( wx.SystemSettings.GetFont( wx.SYS_DEFAULT_GUI_FONT ) )
			
			( text_x, text_y ) = dc.GetTextExtent( collections_string )
			
			top_left_x = width - text_x - CC.THUMBNAIL_BORDER
			top_left_y = height - text_y - CC.THUMBNAIL_BORDER
			
			dc.SetBrush( wx.Brush( CC.COLOUR_UNSELECTED ) )
			
			dc.SetTextForeground( CC.COLOUR_SELECTED_DARK )
			
			dc.SetPen( wx.TRANSPARENT_PEN )
			
			dc.DrawRectangle( top_left_x - 1, top_left_y - 1, text_x + 2, text_y + 2 )
			
			dc.DrawText( collections_string, top_left_x, top_left_y )
			
		
		siblings_manager = HC.app.GetManager( 'tag_siblings' )
		
		upper_info_string = ''
		
		if len( creators ) > 0:
			
			creators = siblings_manager.CollapseNamespacedTags( 'creator', creators )
			
			upper_info_string = ', '.join( creators )
			
			if len( series ) > 0 or len( titles ) > 0: upper_info_string += ' - '
			
		
		if len( series ) > 0:
			
			series = siblings_manager.CollapseNamespacedTags( 'series', series )
			
			upper_info_string += ', '.join( series )
			
		elif len( titles ) > 0:
			
			titles = siblings_manager.CollapseNamespacedTags( 'title', titles )
			
			upper_info_string += ', '.join( titles )
			
		
		if len( upper_info_string ) > 0:
			
			dc.SetFont( wx.SystemSettings.GetFont( wx.SYS_DEFAULT_GUI_FONT ) )
			
			( text_x, text_y ) = dc.GetTextExtent( upper_info_string )
			
			top_left_x = int( ( width - text_x ) / 2 )
			top_left_y = CC.THUMBNAIL_BORDER
			
			dc.SetBrush( wx.Brush( CC.COLOUR_UNSELECTED ) )
			
			dc.SetTextForeground( CC.COLOUR_SELECTED_DARK )
			
			dc.SetPen( wx.TRANSPARENT_PEN )
			
			dc.DrawRectangle( 0, top_left_y - 1, width, text_y + 2 )
			
			dc.DrawText( upper_info_string, top_left_x, top_left_y )
			
		
		dc.SetBrush( wx.TRANSPARENT_BRUSH )
		
		if not local:
			
			if self._selected: rgb = HC.options[ 'gui_colours' ][ 'thumb_border_remote_selected' ]
			else: rgb = HC.options[ 'gui_colours' ][ 'thumb_border_remote' ]
			
		else:
			
			if self._selected: rgb = HC.options[ 'gui_colours' ][ 'thumb_border_selected' ]
			else: rgb = HC.options[ 'gui_colours' ][ 'thumb_border' ]
			
		
		dc.SetPen( wx.Pen( wx.Colour( *rgb ), style=wx.SOLID ) )
		
		dc.DrawRectangle( 0, 0, width, height )
		
		locations_manager = self.GetLocationsManager()
		
		if inbox: dc.DrawBitmap( CC.GlobalBMPs.inbox_bmp, width - 18, 0 )
		elif HC.LOCAL_FILE_SERVICE_KEY in locations_manager.GetPending(): dc.DrawBitmap( CC.GlobalBMPs.downloading_bmp, width - 18, 0 )
		
		if self._dump_status == CC.DUMPER_DUMPED_OK: dc.DrawBitmap( CC.GlobalBMPs.dump_ok, width - 18, 18 )
		elif self._dump_status == CC.DUMPER_RECOVERABLE_ERROR: dc.DrawBitmap( CC.GlobalBMPs.dump_recoverable, width - 18, 18 )
		elif self._dump_status == CC.DUMPER_UNRECOVERABLE_ERROR: dc.DrawBitmap( CC.GlobalBMPs.dump_fail, width - 18, 18 )
		
		if self.IsCollection():
			
			dc.DrawBitmap( CC.GlobalBMPs.collection_bmp, 1, height - 17 )
			
			num_files_str = HC.u( len( self._hashes ) )
			
			dc.SetFont( wx.SystemSettings.GetFont( wx.SYS_DEFAULT_GUI_FONT ) )
			
			( text_x, text_y ) = dc.GetTextExtent( num_files_str )
			
			dc.SetBrush( wx.Brush( CC.COLOUR_UNSELECTED ) )
			
			dc.SetTextForeground( CC.COLOUR_SELECTED_DARK )
			
			dc.SetPen( wx.TRANSPARENT_PEN )
			
			dc.DrawRectangle( 17, height - text_y - 3, text_x + 2, text_y + 2 )
			
			dc.DrawText( num_files_str, 18, height - text_y - 2 )
			
		
		if self._file_service_key == HC.LOCAL_FILE_SERVICE_KEY:
			
			if len( locations_manager.GetPendingRemote() ) > 0: dc.DrawBitmap( CC.GlobalBMPs.file_repository_pending_bmp, 0, 0 )
			elif len( locations_manager.GetCurrentRemote() ) > 0: dc.DrawBitmap( CC.GlobalBMPs.file_repository_bmp, 0, 0 )
			
		elif self._file_service_key in locations_manager.GetCurrentRemote():
			
			if self._file_service_key in locations_manager.GetPetitionedRemote(): dc.DrawBitmap( CC.GlobalBMPs.file_repository_petitioned_bmp, 0, 0 )
			
		
		return bmp
		
	
	def IsLoaded( self ): return self._hydrus_bmp is not None
	
	def ReloadFromDB( self ):
		
		self._my_dimensions = CC.AddPaddingToDimensions( HC.options[ 'thumbnail_dimensions' ], CC.THUMBNAIL_BORDER * 2 )
		
		if self._hydrus_bmp is not None: self._LoadFromDB()
		
	
	def ReloadFromDBLater( self ):
		
		self._my_dimensions = CC.AddPaddingToDimensions( HC.options[ 'thumbnail_dimensions' ], CC.THUMBNAIL_BORDER * 2 )
		
		self._hydrus_bmp = None
		
	
	def SetBmp( self, bmp ): self._hydrus_bmp = bmp
	
class ThumbnailMediaCollection( Thumbnail, ClientGUIMixins.MediaCollection ):
	
	def __init__( self, file_service_key, media_results ):
		
		ClientGUIMixins.MediaCollection.__init__( self, file_service_key, media_results )
		Thumbnail.__init__( self, file_service_key )
		
	
	def ProcessContentUpdate( self, service_key, content_update ):
		
		ClientGUIMixins.MediaCollection.ProcessContentUpdate( self, service_key, content_update )
		
		if service_key == HC.LOCAL_FILE_SERVICE_KEY:
			
			( data_type, action, row ) = content_update.ToTuple()
			
			if action == HC.CONTENT_UPDATE_ADD:
				
				hashes = row
				
				if self.GetDisplayMedia().GetHash() in hashes: self.ReloadFromDB()
				
			
		
	
class ThumbnailMediaSingleton( Thumbnail, ClientGUIMixins.MediaSingleton ):
	
	def __init__( self, file_service_key, media_result ):
		
		ClientGUIMixins.MediaSingleton.__init__( self, media_result )
		Thumbnail.__init__( self, file_service_key )
		
	
	def ProcessContentUpdate( self, service_key, content_update ):
		
		ClientGUIMixins.MediaSingleton.ProcessContentUpdate( self, service_key, content_update )
		
		if service_key == HC.LOCAL_FILE_SERVICE_KEY:
			
			( data_type, action, row ) = content_update.ToTuple()
			
			if action == HC.CONTENT_UPDATE_ADD: self.ReloadFromDB()
			
		
	
