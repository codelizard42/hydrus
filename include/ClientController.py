import gc
import hashlib
import httplib
import HydrusConstants as HC
import HydrusExceptions
import HydrusImageHandling
import HydrusSessions
import HydrusServer
import HydrusTags
import ClientConstants as CC
import ClientDB
import ClientGUI
import ClientGUIDialogs
import os
import random
import shutil
import sqlite3
import sys
import threading
import time
import traceback
import wx
import wx.richtext
from twisted.internet import reactor
from twisted.internet import defer

ID_ANIMATED_EVENT_TIMER = wx.NewId()
ID_MAINTENANCE_EVENT_TIMER = wx.NewId()

class Controller( wx.App ):
    
    def _Read( self, action, *args, **kwargs ): return self._db.Read( action, HC.HIGH_PRIORITY, *args, **kwargs )
    
    def _Write( self, action, priority, synchronous, *args, **kwargs ): return self._db.Write( action, priority, synchronous, *args, **kwargs )
    
    def ClearCaches( self ):
        
        self._thumbnail_cache.Clear()
        self._fullscreen_image_cache.Clear()
        self._preview_image_cache.Clear()
        
    
    def Clipboard( self, type, data ):
        
        # need this cause can't do it in a non-gui thread
        
        if type == 'paths':
            
            paths = data
            
            if wx.TheClipboard.Open():
                
                data = wx.DataObjectComposite()
                
                file_data = wx.FileDataObject()
                
                for path in paths: file_data.AddFile( path )
                
                text_data = wx.TextDataObject( os.linesep.join( paths ) )
                
                data.Add( file_data, True )
                data.Add( text_data, False )
                
                wx.TheClipboard.SetData( data )
                
                wx.TheClipboard.Close()
                
            else: wx.MessageBox( 'Could not get permission to access the clipboard!' )
            
        elif type == 'text':
            
            text = data
            
            if wx.TheClipboard.Open():
                
                data = wx.TextDataObject( text )
                
                wx.TheClipboard.SetData( data )
                
                wx.TheClipboard.Close()
                
            else: wx.MessageBox( 'I could not get permission to access the clipboard.' )
            
        
    
    def DeleteSessionKey( self, service_identifier ): self._session_manager.DeleteSessionKey( service_identifier )
    
    def EventAnimatedTimer( self, event ):
        
        del gc.garbage[:]
        
        HC.pubsub.pub( 'animated_tick' )
        
    
    def EventMaintenanceTimer( self, event ):
        
        if HC.GetNow() - self._last_idle_time > 60 * 60: # a long time, so we probably just woke up from a sleep
            
            self._last_idle_time = HC.GetNow()
            
        
        if HC.GetNow() - self._last_idle_time > 20 * 60: # 20 mins since last user-initiated db request
            
            self.MaintainDB()
            
        
        HC.pubsub.pub( 'clear_closed_pages' )
        
    
    def EventPubSub( self, event ):
        
        HC.busy_doing_pubsub = True
        
        try: HC.pubsub.WXProcessQueueItem()
        finally: HC.busy_doing_pubsub = False
        
    
    def GetFullscreenImageCache( self ): return self._fullscreen_image_cache
    
    def GetGUI( self ): return self._gui
    
    def GetLog( self ): return self._log
    
    def GetNamespaceBlacklistsManager( self ): return self._namespace_blacklists_manager
    
    def GetPreviewImageCache( self ): return self._preview_image_cache
    
    def GetSessionKey( self, service_identifier ): return self._session_manager.GetSessionKey( service_identifier )
    
    def GetTagParentsManager( self ): return self._tag_parents_manager
    
    def GetTagSiblingsManager( self ): return self._tag_siblings_manager
    
    def GetThumbnailCache( self ): return self._thumbnail_cache
    
    def GetUndoManager( self ): return self._undo_manager
    
    def GetWebCookies( self, name ): return self._web_session_manager.GetCookies( name )
    
    def MaintainDB( self ):
        
        sys.stdout.flush()
        sys.stderr.flush()
        
        gc.collect()
        
        now = HC.GetNow()
        
        shutdown_timestamps = self.Read( 'shutdown_timestamps' )
        
        if now - shutdown_timestamps[ CC.SHUTDOWN_TIMESTAMP_VACUUM ] > 86400 * 5: self.Write( 'vacuum' )
        # try no fatten, since we made the recent A/C changes
        #if now - shutdown_timestamps[ CC.SHUTDOWN_TIMESTAMP_FATTEN_AC_CACHE ] > 50000: self.Write( 'fatten_autocomplete_cache' )
        if now - shutdown_timestamps[ CC.SHUTDOWN_TIMESTAMP_DELETE_ORPHANS ] > 86400 * 3: self.Write( 'delete_orphans' )
        
    
    def OnInit( self ):
    
        HC.app = self
        
        self._local_service = None
        self._server = None
        
        init_result = True
        
        try:
            
            try:
                
                def make_temp_files_deletable( function_called, path, traceback_gumpf ):
                    
                    os.chmod( path, stat.S_IWRITE )
                    
                    function_called( path ) # try again
                    
                
                if os.path.exists( HC.TEMP_DIR ): shutil.rmtree( HC.TEMP_DIR, onerror = make_temp_files_deletable )
                
            except: pass
            
            try:
                
                if not os.path.exists( HC.TEMP_DIR ): os.mkdir( HC.TEMP_DIR )
                
            except: pass
            
            self._splash = ClientGUI.FrameSplash()
            
            self.SetSplashText( 'log' )
            
            self._log = CC.Log()
            
            self.SetSplashText( 'db' )
            
            db_initialised = False
            
            while not db_initialised:
                
                try:
                    
                    self._db = ClientDB.DB()
                    
                    db_initialised = True
                    
                except HydrusExceptions.DBAccessException as e:
                    
                    try: print( HC.u( e ) )
                    except: print( repr( HC.u( e ) ) )
                    
                    message = 'This instance of the client had a problem connecting to the database, which probably means an old instance is still closing.'
                    message += os.linesep + os.linesep
                    message += 'If the old instance does not close for a _very_ long time, you can usually safely force-close it from task manager.'
                    
                    with ClientGUIDialogs.DialogYesNo( None, message, yes_label = 'wait a bit, then try again', no_label = 'quit now' ) as dlg:
                        
                        if dlg.ShowModal() == wx.ID_YES: time.sleep( 3 )
                        else: raise HydrusExceptions.PermissionException()
                        
                    
                
            
            threading.Thread( target = self._db.MainLoop, name = 'Database Main Loop' ).start()
            
            if HC.options[ 'password' ] is not None:
                
                self.SetSplashText( 'waiting for password' )
                
                while True:
                    
                    with wx.PasswordEntryDialog( None, 'Enter your password', 'Enter password' ) as dlg:
                        
                        if dlg.ShowModal() == wx.ID_OK:
                            
                            if hashlib.sha256( dlg.GetValue() ).digest() == HC.options[ 'password' ]: break
                            
                        else: raise HydrusExceptions.PermissionException()
                        
                    
                
            
            self.SetSplashText( 'caches' )
            
            self._session_manager = HydrusSessions.HydrusSessionManagerClient()
            self._web_session_manager = HydrusSessions.WebSessionManagerClient()
            self._namespace_blacklists_manager = HydrusTags.NamespaceBlacklistsManager()
            self._tag_parents_manager = HydrusTags.TagParentsManager()
            self._tag_siblings_manager = HydrusTags.TagSiblingsManager()
            self._undo_manager = CC.UndoManager()
            
            self._fullscreen_image_cache = CC.RenderedImageCache( 'fullscreen' )
            self._preview_image_cache = CC.RenderedImageCache( 'preview' )
            
            self._thumbnail_cache = CC.ThumbnailCache()
            
            CC.GlobalBMPs.STATICInitialise()
            
            self.SetSplashText( 'gui' )
            
            self._gui = ClientGUI.FrameGUI()
            
            HC.pubsub.sub( self, 'Clipboard', 'clipboard' )
            HC.pubsub.sub( self, 'RestartServer', 'restart_server' )
            
            self.Bind( HC.EVT_PUBSUB, self.EventPubSub )
            
            # this is because of some bug in wx C++ that doesn't add these by default
            wx.richtext.RichTextBuffer.AddHandler( wx.richtext.RichTextHTMLHandler() )
            wx.richtext.RichTextBuffer.AddHandler( wx.richtext.RichTextXMLHandler() )
            
            self.Bind( wx.EVT_TIMER, self.EventAnimatedTimer, id = ID_ANIMATED_EVENT_TIMER )
            
            self._animated_event_timer = wx.Timer( self, ID_ANIMATED_EVENT_TIMER )
            self._animated_event_timer.Start( 1000, wx.TIMER_CONTINUOUS )
            
            self.SetSplashText( 'starting daemons' )
            
            if HC.is_first_start: self._gui.DoFirstStart()
            if HC.is_db_updated: wx.CallLater( 0, HC.pubsub.pub, 'message', HC.Message( HC.MESSAGE_TYPE_TEXT, 'The client has updated to version ' + HC.u( HC.SOFTWARE_VERSION ) + '!' ) )
            
            self.RestartServer()
            self._db.StartDaemons()
            
            self._last_idle_time = 0.0
            
            self.Bind( wx.EVT_TIMER, self.EventMaintenanceTimer, id = ID_MAINTENANCE_EVENT_TIMER )
            
            self._maintenance_event_timer = wx.Timer( self, ID_MAINTENANCE_EVENT_TIMER )
            self._maintenance_event_timer.Start( 20 * 60000, wx.TIMER_CONTINUOUS )
            
        except sqlite3.OperationalError as e:
            
            message = 'Database error!' + os.linesep + os.linesep + traceback.format_exc()
            
            print message
            
            wx.MessageBox( message )
            
            init_result = False
            
        except HydrusExceptions.PermissionException as e: init_result = False
        except:
            
            wx.MessageBox( 'Woah, bad error:' + os.linesep + os.linesep + traceback.format_exc() )
            
            try: self._splash.Close()
            except: pass
            
            init_result = False
            
        
        self._splash.Close()
        
        return init_result
        
    
    def PrepStringForDisplay( self, text ):
        
        if HC.options[ 'gui_capitalisation' ]: return text
        else: return text.lower()
        
    
    def Read( self, action, *args, **kwargs ):
        
        self._last_idle_time = HC.GetNow()
        
        return self._Read( action, *args, **kwargs )
        
    
    def ReadDaemon( self, action, *args, **kwargs ):
        
        result = self._Read( action, *args, **kwargs )
        
        time.sleep( 0.1 )
        
        return result
        
    
    def RestartServer( self ):
        
        port = HC.options[ 'local_port' ]
        
        def TWISTEDRestartServer():
            
            def StartServer( *args, **kwargs ):
                
                try:
                    
                    connection = httplib.HTTPConnection( '127.0.0.1', port, timeout = 10 )
                    
                    try:
                        
                        connection.connect()
                        connection.close()
                        
                        message = 'Something was already bound to port ' + HC.u( port )
                        
                        wx.CallAfter( HC.pubsub.pub, 'message', HC.Message( HC.MESSAGE_TYPE_TEXT, message ) )
                        
                    except:
                        
                        local_file_server_service_identifier = HC.ServerServiceIdentifier( 'local file', HC.LOCAL_FILE )
                        
                        self._local_service = reactor.listenTCP( port, HydrusServer.HydrusServiceLocal( local_file_server_service_identifier, 'hello' ) )
                        
                        connection = httplib.HTTPConnection( '127.0.0.1', port, timeout = 10 )
                        
                        try:
                            
                            connection.connect()
                            connection.close()
                            
                        except:
                            
                            message = 'Tried to bind port ' + HC.u( port ) + ' but it failed'
                            
                            wx.CallAfter( HC.pubsub.pub, 'message', HC.Message( HC.MESSAGE_TYPE_TEXT, message ) )
                            
                        
                    
                except Exception as e:
                    
                    wx.CallAfter( HC.ShowException, e )
                    
                
            
            if self._local_service is None: StartServer()
            else:
                
                deferred = defer.maybeDeferred( self._local_service.stopListening )
                
                deferred.addCallback( StartServer )
                
            
        
        reactor.callFromThread( TWISTEDRestartServer )
        
    
    def SetSplashText( self, text ):
        
        self._splash.SetText( text )
        self.Yield() # this processes the event queue immediately, so the paint event can occur
        
    
    def StartFileQuery( self, query_key, search_context ):
        
        threading.Thread( target = self.THREADDoFileQuery, name = 'file query', args = ( query_key, search_context ) ).start()
        
    
    def THREADDoFileQuery( self, query_key, search_context ):
        
        try:
            
            query_hash_ids = HC.app.Read( 'file_query_ids', search_context )
            
            query_hash_ids = list( query_hash_ids )
            
            random.shuffle( query_hash_ids )
            
            limit = search_context.GetSystemPredicates().GetLimit()
            
            if limit is not None: query_hash_ids = query_hash_ids[ : limit ]
            
            file_service_identifier = search_context.GetFileServiceIdentifier()
            
            include_current_tags = search_context.IncludeCurrentTags()
            
            media_results = []
            
            include_pending_tags = search_context.IncludePendingTags()
            
            i = 0
            
            base = 256
            
            while i < len( query_hash_ids ):
                
                if query_key.IsCancelled(): return
                
                if i == 0: ( last_i, i ) = ( 0, base )
                else: ( last_i, i ) = ( i, i + base )
                
                sub_query_hash_ids = query_hash_ids[ last_i : i ]
                
                more_media_results = HC.app.Read( 'media_results_from_ids', file_service_identifier, sub_query_hash_ids )
                
                media_results.extend( more_media_results )
                
                HC.pubsub.pub( 'set_num_query_results', len( media_results ), len( query_hash_ids ) )
                
                HC.app.WaitUntilGoodTimeToUseGUIThread()
                
            
            HC.pubsub.pub( 'file_query_done', query_key, media_results )
            
        except Exception as e: HC.ShowException( e )
        
    
    def WaitUntilGoodTimeToUseGUIThread( self ):
        
        while True:
            
            if HC.shutdown: raise Exception( 'Client shutting down!' )
            elif HC.pubsub.NotBusy() and not HC.busy_doing_pubsub: return
            else: time.sleep( 0.0001 )
            
        
    
    def Write( self, action, *args, **kwargs ):
        
        self._last_idle_time = HC.GetNow()
        
        if action == 'content_updates': self._undo_manager.AddCommand( 'content_updates', *args, **kwargs )
        
        return self._Write( action, HC.HIGH_PRIORITY, False, *args, **kwargs )
        
    
    def WriteSynchronous( self, action, *args, **kwargs ):
        
        result = self._Write( action, HC.LOW_PRIORITY, True, *args, **kwargs )
        
        time.sleep( 0.1 )
        
        return result
        
    