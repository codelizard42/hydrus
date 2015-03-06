import bs4
import collections
import httplib
import HydrusConstants as HC
import HydrusExceptions
import HydrusNetworking
import HydrusThreading
import json
import os
import pafy
import re
import threading
import time
import traceback
import urllib
import urlparse
import wx
import zipfile

def ConvertServiceKeysToTagsToServiceKeysToContentUpdates( hash, service_keys_to_tags ):
	
	hashes = set( ( hash, ) )
	
	service_keys_to_content_updates = {}
	
	for ( service_key, tags ) in service_keys_to_tags.items():
		
		if service_key == HC.LOCAL_TAG_SERVICE_KEY: action = HC.CONTENT_UPDATE_ADD
		else: action = HC.CONTENT_UPDATE_PENDING
		
		content_updates = [ HC.ContentUpdate( HC.CONTENT_DATA_TYPE_MAPPINGS, action, ( tag, hashes ) ) for tag in tags ]
		
		service_keys_to_content_updates[ service_key ] = content_updates
		
	
	return service_keys_to_content_updates
	
def GetDownloader( site_type, *args ):
	
	if site_type == HC.SITE_TYPE_BOORU: c = DownloaderBooru
	elif site_type == HC.SITE_TYPE_DEVIANT_ART: c = DownloaderDeviantArt
	elif site_type == HC.SITE_TYPE_GIPHY: c = DownloaderGiphy
	elif site_type == HC.SITE_TYPE_HENTAI_FOUNDRY: c = DownloaderHentaiFoundry
	elif site_type == HC.SITE_TYPE_PIXIV: c = DownloaderPixiv
	elif site_type == HC.SITE_TYPE_TUMBLR: c = DownloaderTumblr
	elif site_type == HC.SITE_TYPE_NEWGROUNDS: c = DownloaderNewgrounds
	
	return c( *args )
	
def ConvertTagsToServiceKeysToTags( tags, advanced_tag_options ):
	
	tags = [ tag for tag in tags if tag is not None ]
	
	service_keys_to_tags = {}
	
	siblings_manager = HC.app.GetManager( 'tag_siblings' )
	parents_manager = HC.app.GetManager( 'tag_parents' )
	
	for ( service_key, namespaces ) in advanced_tag_options.items():
		
		if len( namespaces ) > 0:
			
			tags_to_add_here = []
			
			for namespace in namespaces:
				
				if namespace == '': tags_to_add_here.extend( [ tag for tag in tags if not ':' in tag ] )
				else: tags_to_add_here.extend( [ tag for tag in tags if tag.startswith( namespace + ':' ) ] )
				
			
			tags_to_add_here = HC.CleanTags( tags_to_add_here )
			
			if len( tags_to_add_here ) > 0:
				
				tags_to_add_here = siblings_manager.CollapseTags( tags_to_add_here )
				tags_to_add_here = parents_manager.ExpandTags( service_key, tags_to_add_here )
				
				service_keys_to_tags[ service_key ] = tags_to_add_here
				
			
		
	
	return service_keys_to_tags
	
def GetYoutubeFormats( youtube_url ):
    
    try: p = pafy.Pafy( youtube_url )
    except Exception as e:
        
        raise Exception( 'Could not fetch video info from youtube!' + os.linesep + HC.u( e ) )
        
    
    info = { ( s.extension, s.resolution ) : ( s.url, s.title ) for s in p.streams if s.extension in ( 'flv', 'mp4' ) }
    
    return info
    
class Downloader( object ):
	
	def __init__( self ):
		
		self._we_are_done = False
		
		self._report_hooks = []
		
		self._all_urls_so_far = set()
		
		self._num_pages_done = 0
		
	
	def _AddSessionCookies( self, request_headers ): pass
	
	def _FetchData( self, url, request_headers = {}, report_hooks = [], response_to_path = False ):
		
		self._AddSessionCookies( request_headers )
		
		return HC.http.Request( HC.GET, url, request_headers = request_headers, report_hooks = report_hooks, response_to_path = response_to_path )
		
	
	def _GetNextGalleryPageURL( self ): return ''
	
	def _GetNextGalleryPageURLs( self ): return ( self._GetNextGalleryPageURL(), )
	
	def AddReportHook( self, hook ): self._report_hooks.append( hook )
	
	def ClearReportHooks( self ): self._report_hooks = []
	
	def GetAnotherPage( self ):
		
		if self._we_are_done: return []
		
		urls = self._GetNextGalleryPageURLs()
		
		url_info = []
		
		for url in urls:
			
			data = self._FetchData( url )
			
			page_of_url_info = self._ParseGalleryPage( data, url )
			
			# stop ourselves getting into an accidental infinite loop
			
			url_info += [ info for info in page_of_url_info if info[0] not in self._all_urls_so_far ]
			
			self._all_urls_so_far.update( [ info[0] for info in url_info ] )
			
			# now url_info only contains new url info
			
		
		self._num_pages_done += 1
		
		return url_info
		
	
	def GetFile( self, url, *args ): return self._FetchData( url, report_hooks = self._report_hooks, response_to_path = True )
	
	def GetFileAndTags( self, url, *args ):
		
		temp_path = self.GetFile( url, *args )
		tags = self.GetTags( url, *args )
		
		return ( temp_path, tags )
		
	
	def GetTags( self, url ): pass
	
	def SetupGallerySearch( self ): pass
	
class DownloaderBooru( Downloader ):
	
	def __init__( self, booru, tags ):
		
		self._booru = booru
		self._tags = tags
		
		self._gallery_advance_num = None
		
		( self._search_url, self._advance_by_page_num, self._search_separator, self._thumb_classname ) = booru.GetGalleryParsingInfo()
		
		Downloader.__init__( self )
		
	
	def _GetNextGalleryPageURL( self ):
		
		if self._advance_by_page_num: index = 1 + self._num_pages_done
		else:
			
			if self._gallery_advance_num is None: index = 0
			else: index = self._num_pages_done * self._gallery_advance_num
			
		
		return self._search_url.replace( '%tags%', self._search_separator.join( [ urllib.quote( tag ) for tag in self._tags ] ) ).replace( '%index%', HC.u( index ) )
		
	
	def _ParseGalleryPage( self, html, url_base ):
		
		urls_set = set()
		urls = []
		
		soup = bs4.BeautifulSoup( html )
		
		# this catches 'post-preview' along with 'post-preview not-approved' sort of bullshit
		def starts_with_classname( classname ): return classname is not None and classname.startswith( self._thumb_classname )
		
		thumbnails = soup.find_all( class_ = starts_with_classname )
		
		# this is a sankaku thing
		popular_thumbnail_parent = soup.find( id = 'popular-preview' )
		
		if popular_thumbnail_parent is not None:
			
			popular_thumbnails = popular_thumbnail_parent.find_all( class_ = starts_with_classname )
			
			thumbnails = thumbnails[ len( popular_thumbnails ) : ]
			
		
		if self._gallery_advance_num is None:
			
			if len( thumbnails ) == 0: self._we_are_done = True
			else: self._gallery_advance_num = len( thumbnails )
			
		
		for thumbnail in thumbnails:
			
			links = thumbnail.find_all( 'a' )
			
			if thumbnail.name == 'a': links.append( thumbnail )
			
			for link in links:
				
				if link.string is not None and link.string == 'Image Only': continue # rule 34 @ paheal fix
				
				url = link[ 'href' ]
				
				url = urlparse.urljoin( url_base, url )
				
				if url not in urls_set:
					
					urls_set.add( url )
					urls.append( ( url, ) )
					
				
			
		
		return urls
		
	
	def _ParseImagePage( self, html, url_base ):
		
		( search_url, search_separator, advance_by_page_num, thumb_classname, image_id, image_data, tag_classnames_to_namespaces ) = self._booru.GetData()
		
		soup = bs4.BeautifulSoup( html )
		
		image_base = None
		
		if image_id is not None:
			
			image = soup.find( id = image_id )
			
			if image is None:
				
				image_string = soup.find( text = re.compile( 'Save this file' ) )
				
				if image_string is None: image_string = soup.find( text = re.compile( 'Save this video' ) )
				
				image = image_string.parent
				
				image_url = image[ 'href' ]
				
			else:
				
				if image.name in ( 'img', 'video' ):
					
					image_url = image[ 'src' ]
					
					if 'sample/sample-' in image_url:
						
						# danbooru resized image
						
						image = soup.find( id = 'image-resize-link' )
						
						image_url = image[ 'href' ]
						
					
				elif image.name == 'a':
					
					image_url = image[ 'href' ]
					
				
			
		
		if image_data is not None:
			
			links = soup.find_all( 'a' )
			
			for link in links:
				
				if link.string == image_data: image_url = link[ 'href' ]
				
			
		
		image_url = urlparse.urljoin( url_base, image_url )
		
		tags = []
		
		for ( tag_classname, namespace ) in tag_classnames_to_namespaces.items():
			
			tag_list_entries = soup.find_all( class_ = tag_classname )
			
			for tag_list_entry in tag_list_entries:
				
				links = tag_list_entry.find_all( 'a' )
				
				if tag_list_entry.name == 'a': links.append( tag_list_entry )
				
				for link in links:
					
					if link.string not in ( '?', '-', '+' ):
						
						if namespace == '': tags.append( link.string )
						else: tags.append( namespace + ':' + link.string )
						
					
				
			
		
		return ( image_url, tags )
		
	
	def _GetFileURLAndTags( self, url ):
		
		html = self._FetchData( url )
		
		return self._ParseImagePage( html, url )
		
	
	def GetFile( self, url ):
		
		( file_url, tags ) = self._GetFileURLAndTags( url )
		
		temp_path = self._FetchData( file_url, report_hooks = self._report_hooks, response_to_path = True )
		
		return temp_path
		
	
	def GetFileAndTags( self, url ):
		
		( file_url, tags ) = self._GetFileURLAndTags( url )
		
		temp_path = self._FetchData( file_url, report_hooks = self._report_hooks, response_to_path = True )
		
		return ( temp_path, tags )
		
	
	def GetTags( self, url ):
		
		( file_url, tags ) = self._GetFileURLAndTags( url )
		
		return tags
		
	
class DownloaderDeviantArt( Downloader ):
	
	def __init__( self, artist ):
		
		self._gallery_url = 'http://' + artist + '.deviantart.com/gallery/?catpath=/&offset='
		self._artist = artist
		
		Downloader.__init__( self )
		
	
	def _GetNextGalleryPageURL( self ): return self._gallery_url + HC.u( self._num_pages_done * 24 )
	
	def _ParseGalleryPage( self, html, url_base ):
		
		results = []
		
		soup = bs4.BeautifulSoup( html )
		
		thumbs_container = soup.find( class_ = 'zones-container' )
		
		def starts_with_thumb( classname ): return classname is not None and classname.startswith( 'thumb' )
		
		links = thumbs_container.find_all( 'a', class_ = starts_with_thumb )
		
		for link in links:
			
			try: # starts_with_thumb picks up some false positives, but they break
				
				page_url = link[ 'href' ] # something in the form of blah.da.com/art/blah-123456
				
				raw_title = link[ 'title' ] # sweet dolls by AngeniaC, date, blah blah blah
				
				raw_title_reversed = raw_title[::-1] # trAtnaiveD no CainegnA yb sllod teews
				
				( creator_and_gumpf_reversed, title_reversed ) = raw_title_reversed.split( ' yb ', 1 )
				
				title = title_reversed[::-1] # sweet dolls
				
				tags = []
				
				tags.append( 'title:' + title )
				tags.append( 'creator:' + self._artist )
				
				results.append( ( page_url, tags ) )
				
			except: pass
			
		
		return results
		
	
	def _ParseImagePage( self, html ):
		
		soup = bs4.BeautifulSoup( html )
		
		# if can find download link:
		if False:
			
			pass # go fetch the popup page using tokens as appropriate. feels like it needs the GET token and a referrer, as middle click just redirects back to image page
			
		else:
			
			img = soup.find( class_ = 'dev-content-full' )
			
			src = img[ 'src' ]
			
			return src
			
		
	
	def _GetFileURL( self, url ):
		
		html = self._FetchData( url )
		
		return self._ParseImagePage( html )
		
	
	def GetFile( self, url, tags ):
		
		file_url = self._GetFileURL( url )
		
		temp_path = self._FetchData( file_url, report_hooks = self._report_hooks, response_to_path = True )
		
		return temp_path
		
	
	def GetTags( self, url, tags ): return tags
	
class DownloaderGiphy( Downloader ):
	
	def __init__( self, tag ):
		
		self._gallery_url = 'http://giphy.com/api/gifs?tag=' + urllib.quote( tag.replace( ' ', '+' ) ) + '&page='
		
		Downloader.__init__( self )
		
	
	def _GetNextGalleryPageURL( self ): return self._gallery_url + HC.u( self._num_pages_done + 1 )
	
	def _ParseGalleryPage( self, data, url_base ):
		
		json_dict = json.loads( data )
		
		if 'data' in json_dict:
			
			json_data = json_dict[ 'data' ]
			
			return [ ( d[ 'image_original_url' ], d[ 'id' ] ) for d in json_data ]
			
		else: return []
		
	
	def GetTags( self, url, id ):
		
		url = 'http://giphy.com/api/gifs/' + HC.u( id )
		
		try:
			
			raw_json = self._FetchData( url )
			
			json_dict = json.loads( raw_json )
			
			tags_data = json_dict[ 'data' ][ 'tags' ]
			
			tags = [ tag_data[ 'name' ] for tag_data in tags_data ]
			
		except Exception as e:
			
			HC.ShowException( e )
			
			tags = []
			
		
		return tags
		
	
class DownloaderHentaiFoundry( Downloader ):
    
    def __init__( self, query_type, query, advanced_hentai_foundry_options ):
        
        self._query_type = query_type
        self._query = query
        self._advanced_hentai_foundry_options = advanced_hentai_foundry_options
        
        Downloader.__init__( self )
        
    
    def _AddSessionCookies( self, request_headers ):
        
        manager = HC.app.GetManager( 'web_sessions' )
        
        cookies = manager.GetCookies( 'hentai foundry' )
        
        HydrusNetworking.AddCookiesToHeaders( cookies, request_headers )
        
    
    def _GetFileURLAndTags( self, url ):
        
        html = self._FetchData( url )
        
        return self._ParseImagePage( html, url )
        
    
    def _GetNextGalleryPageURL( self ):
        
        if self._query_type in ( 'artist', 'artist pictures' ):
            
            artist = self._query
            
            gallery_url = 'http://www.hentai-foundry.com/pictures/user/' + artist
            
            return gallery_url + '/page/' + HC.u( self._num_pages_done + 1 )
            
        elif self._query_type == 'artist scraps':
            
            artist = self._query
            
            gallery_url = 'http://www.hentai-foundry.com/pictures/user/' + artist + '/scraps'
            
            return gallery_url + '/page/' + HC.u( self._num_pages_done + 1 )
            
        elif self._query_type == 'tags':
            
            tags = self._query
            
            return 'http://www.hentai-foundry.com/search/pictures?query=' + '+'.join( tags ) + '&search_in=all&scraps=-1&page=' + HC.u( self._num_pages_done + 1 )
            # scraps = 0 hide
            # -1 means show both
            # 1 means scraps only. wetf
            
        
    
    def _ParseGalleryPage( self, html, url_base ):
        
        urls_set = set()
        
        soup = bs4.BeautifulSoup( html )
        
        def correct_url( href ):
            
            # a good url is in the form "/pictures/user/artist_name/file_id/title"
            
            if href.count( '/' ) == 5 and href.startswith( '/pictures/user/' ):
                
                ( nothing, pictures, user, artist_name, file_id, title ) = href.split( '/' )
                
                # /pictures/user/artist_name/page/3
                if file_id != 'page': return True
                
            
            return False
            
        
        links = soup.find_all( 'a', href = correct_url )
        
        urls = [ 'http://www.hentai-foundry.com' + link['href'] for link in links ]
        
        result_urls = []
        
        for url in urls:
            
            if url not in urls_set:
                
                urls_set.add( url )
                
                result_urls.append( ( url, ) )
                
            
        
        # this is copied from old code. surely we can improve it?
        if 'class="next"' not in html: self._we_are_done = True
        
        return result_urls
        
    
    def _ParseImagePage( self, html, url_base ):
        
        # can't parse this easily normally because HF is a pain with the preview->click to see full size business.
        # find http://pictures.hentai-foundry.com//
        # then extend it to http://pictures.hentai-foundry.com//k/KABOS/172144.jpg
        # the .jpg bit is what we really need, but whatever
        try:
            
            index = html.index( 'pictures.hentai-foundry.com' )
            
            image_url = html[ index : index + 256 ]
            
            if '"' in image_url: ( image_url, gumpf ) = image_url.split( '"', 1 )
            if '&#039;' in image_url: ( image_url, gumpf ) = image_url.split( '&#039;', 1 )
            
            image_url = 'http://' + image_url
            
        except Exception as e:
            
            raise Exception( 'Could not parse image url!' + os.linesep + HC.u( e ) )
            
        
        soup = bs4.BeautifulSoup( html )
        
        tags = []
        
        try:
            
            title = soup.find( 'title' )
            
            ( data, nothing ) = HC.u( title.string ).split( ' - Hentai Foundry' )
            
            data_reversed = data[::-1] # want to do it right-side first, because title might have ' by ' in it
            
            ( artist_reversed, title_reversed ) = data_reversed.split( ' yb ' )
            
            artist = artist_reversed[::-1]
            
            title = title_reversed[::-1]
            
            tags.append( 'creator:' + artist )
            tags.append( 'title:' + title )
            
        except: pass
        
        tag_links = soup.find_all( 'a', rel = 'tag' )
        
        for tag_link in tag_links: tags.append( tag_link.string )
        
        return ( image_url, tags )
        
    
    def GetFile( self, url ):
        
        ( file_url, tags ) = self._GetFileURLAndTags( url )
        
        temp_path = self._FetchData( file_url, report_hooks = self._report_hooks, response_to_path = True )
        
        return temp_path
        
    
    def GetFileAndTags( self, url ):
        
        ( file_url, tags ) = self._GetFileURLAndTags( url )
        
        temp_path = self._FetchData( file_url, report_hooks = self._report_hooks, response_to_path = True )
        
        return ( temp_path, tags )
        
    
    def GetTags( self, url ):
        
        ( file_url, tags ) = self._GetFileURLAndTags( url )
        
        return tags
        
    
    def SetupGallerySearch( self ):
        
        manager = HC.app.GetManager( 'web_sessions' )
        
        cookies = manager.GetCookies( 'hentai foundry' )
        
        raw_csrf = cookies[ 'YII_CSRF_TOKEN' ] # 19b05b536885ec60b8b37650a32f8deb11c08cd1s%3A40%3A%222917dcfbfbf2eda2c1fbe43f4d4c4ec4b6902b32%22%3B
        
        processed_csrf = urllib.unquote( raw_csrf ) # 19b05b536885ec60b8b37650a32f8deb11c08cd1s:40:"2917dcfbfbf2eda2c1fbe43f4d4c4ec4b6902b32";
        
        csrf_token = processed_csrf.split( '"' )[1] # the 2917... bit
        
        self._advanced_hentai_foundry_options[ 'YII_CSRF_TOKEN' ] = csrf_token
        
        body = urllib.urlencode( self._advanced_hentai_foundry_options )
        
        request_headers = {}
        request_headers[ 'Content-Type' ] = 'application/x-www-form-urlencoded'
        
        self._AddSessionCookies( request_headers )
        
        HC.http.Request( HC.POST, 'http://www.hentai-foundry.com/site/filters', request_headers = request_headers, body = body )
        
    
class DownloaderNewgrounds( Downloader ):
	
	def __init__( self, query ):
		
		self._query = query
		
		Downloader.__init__( self )
		
	
	def _GetFileURLAndTags( self, url ):
		
		html = self._FetchData( url )
		
		return self._ParseImagePage( html, url )
		
	
	def _GetNextGalleryPageURLs( self ):
		
		artist = self._query
		
		gallery_urls = []
		
		gallery_urls.append( 'http://' + artist + '.newgrounds.com/games/' )
		gallery_urls.append( 'http://' + artist + '.newgrounds.com/movies/' )
		
		self._we_are_done = True
		
		return gallery_urls
		
	
	def _ParseGalleryPage( self, html, url_base ):
		
		soup = bs4.BeautifulSoup( html )
		
		fatcol = soup.find( 'div', class_ = 'fatcol' )
		
		links = fatcol.find_all( 'a' )
		
		urls_set = set()
		
		result_urls = []
		
		for link in links:
			
			try:
				
				url = link[ 'href' ]
				
				if url not in urls_set:
					
					if url.startswith( 'http://www.newgrounds.com/portal/view/' ): 
						
						urls_set.add( url )
						
						result_urls.append( ( url, ) )
						
					
				
			except: pass
			
		
		return result_urls
		
	
	def _ParseImagePage( self, html, url_base ):
		
		soup = bs4.BeautifulSoup( html )
		
		tags = set()
		
		author_links = soup.find( 'ul', class_ = 'authorlinks' )
		
		if author_links is not None:
			
			authors = set()
			
			links = author_links.find_all( 'a' )
			
			for link in links:
				
				try:
					
					href = link[ 'href' ] # http://warlord-of-noodles.newgrounds.com
					
					creator = href.replace( 'http://', '' ).replace( '.newgrounds.com', '' )
					
					tags.add( u'creator:' + creator )
					
				except: pass
				
			
		
		try:
			
			title = soup.find( 'title' )
			
			tags.add( u'title:' + title.string )
			
		except: pass
		
		all_links = soup.find_all( 'a' )
		
		for link in all_links:
			
			try:
				
				href = link[ 'href' ]
				
				if '/browse/tag/' in href: tags.add( link.string )
				
			except: pass
			
		
		#
		
		try:
			
			components = html.split( '"http://uploads.ungrounded.net/' )
			
			# there is sometimes another bit of api flash earlier on that we don't want
			# it is called http://uploads.ungrounded.net/apiassets/sandbox.swf
			
			if len( components ) == 2: flash_url = components[1]
			else: flash_url = components[2]
			
			flash_url = flash_url.split( '"', 1 )[0]
			
			flash_url = 'http://uploads.ungrounded.net/' + flash_url
			
		except: raise Exception( 'Could not find the swf file! It was probably an mp4!' )
		
		return ( flash_url, tags )
		
	
	def GetFile( self, url ):
		
		( file_url, tags ) = self._GetFileURLAndTags( url )
		
		temp_path = self._FetchData( file_url, report_hooks = self._report_hooks, response_to_path = True )
		
		return temp_path
		
	
	def GetFileAndTags( self, url ):
		
		( file_url, tags ) = self._GetFileURLAndTags( url )
		
		temp_path = self._FetchData( file_url, report_hooks = self._report_hooks, response_to_path = True )
		
		return ( temp_path, tags )
		
	
	def GetTags( self, url ):
		
		( file_url, tags ) = self._GetFileURLAndTags( url )
		
		return tags
		
	
class DownloaderPixiv( Downloader ):
	
	def __init__( self, query_type, query ):
		
		self._query_type = query_type
		self._query = query
		
		Downloader.__init__( self )
		
	
	def _AddSessionCookies( self, request_headers ):
		
		manager = HC.app.GetManager( 'web_sessions' )
		
		cookies = manager.GetCookies( 'pixiv' )
		
		HydrusNetworking.AddCookiesToHeaders( cookies, request_headers )
		
	
	def _GetNextGalleryPageURL( self ):
		
		if self._query_type == 'artist_id':
			
			artist_id = self._query
			
			gallery_url = 'http://www.pixiv.net/member_illust.php?id=' + HC.u( artist_id )
			
		elif self._query_type == 'tags':
			
			tag = self._query
			
			gallery_url = 'http://www.pixiv.net/search.php?word=' + urllib.quote( tag.encode( 'utf-8' ) ) + '&s_mode=s_tag_full&order=date_d'
			
		
		return gallery_url + '&p=' + HC.u( self._num_pages_done + 1 )
		
	
	def _ParseGalleryPage( self, html, url_base ):
		
		results = []
		
		soup = bs4.BeautifulSoup( html )
		
		thumbnail_links = soup.find_all( class_ = 'work' )
		
		for thumbnail_link in thumbnail_links:
			
			url = urlparse.urljoin( url_base, thumbnail_link[ 'href' ] ) # http://www.pixiv.net/member_illust.php?mode=medium&illust_id=33500690
			
			results.append( ( url, ) )
			
		
		return results
		
	
	def _ParseImagePage( self, html, page_url ):
		
		if 'member_illust.php?mode=manga' in html: raise Exception( page_url + ' was manga, not a single image, so could not be downloaded.' )
		
		soup = bs4.BeautifulSoup( html )
		
		#
		
		# this is the page that holds the full size of the image.
		# pixiv won't serve the image unless it thinks this page is the referrer
		referral_url = page_url.replace( 'medium', 'big' ) # http://www.pixiv.net/member_illust.php?mode=big&illust_id=33500690
		
		#
		
		works_display = soup.find( class_ = 'works_display' )
		
		img = works_display.find( 'img' )
		
		img_url = img[ 'src' ] # http://i2.pixiv.net/img122/img/amanekukagenoyuragi/34992468_m.png
		
		image_url = img_url.replace( '_m.', '.' ) # http://i2.pixiv.net/img122/img/amanekukagenoyuragi/34992468.png
		
		#
		
		tags = soup.find( 'ul', class_ = 'tags' )
		
		tags = [ a_item.string for a_item in tags.find_all( 'a', class_ = 'text' ) ]
		
		user = soup.find( 'h1', class_ = 'user' )
		
		tags.append( 'creator:' + user.string )
		
		title_parent = soup.find( 'section', class_ = 'work-info' )
		
		title = title_parent.find( 'h1', class_ = 'title' )
		
		tags.append( 'title:' + title.string )
		
		try: tags.append( 'creator:' + image_url.split( '/' )[ -2 ] ) # http://i2.pixiv.net/img02/img/dnosuke/462657.jpg -> dnosuke
		except: pass
		
		return ( referral_url, image_url, tags )
		
	
	def _GetReferralURLFileURLAndTags( self, page_url ):
		
		html = self._FetchData( page_url )
		
		return self._ParseImagePage( html, page_url )
		
	
	def GetFile( self, url ):
		
		( referral_url, image_url, tags ) = self._GetReferralURLFileURLAndTags( url )
		
		request_headers = { 'Referer' : referral_url }
		
		return self._FetchData( image_url, request_headers = request_headers, report_hooks = self._report_hooks, response_to_path = True )
		
	
	def GetFileAndTags( self, url ):
		
		( referral_url, image_url, tags ) = self._GetReferralURLFileURLAndTags( url )
		
		request_headers = { 'Referer' : referral_url }
		
		temp_path = self._FetchData( image_url, request_headers = request_headers, report_hooks = self._report_hooks, response_to_path = True )
		
		return ( temp_path, tags )
		
	
	def GetTags( self, url ):
		
		( referral_url, image_url, tags ) = self._GetReferralURLFileURLAndTags( url )
		
		return tags
		
	
class DownloaderTumblr( Downloader ):
	
	def __init__( self, username ):
		
		self._gallery_url = 'http://' + username + '.tumblr.com/api/read/json?start=%start%&num=50'
		
		Downloader.__init__( self )
		
	
	def _GetNextGalleryPageURL( self ): return self._gallery_url.replace( '%start%', HC.u( self._num_pages_done * 50 ) )
	
	def _ParseGalleryPage( self, data, url_base ):
		
		processed_raw_json = data.split( 'var tumblr_api_read = ' )[1][:-2] # -2 takes a couple newline chars off at the end
		
		json_object = json.loads( processed_raw_json )
		
		results = []
		
		if 'posts' in json_object:
			
			for post in json_object[ 'posts' ]:
				
				if 'tags' in post: tags = post[ 'tags' ]
				else: tags = []
				
				post_type = post[ 'type' ]
				
				if post_type == 'photo':
					
					if len( post[ 'photos' ] ) == 0:
						
						try: results.append( ( post[ 'photo-url-1280' ], tags ) )
						except: pass
						
					else:
						
						for photo in post[ 'photos' ]:
							
							try: results.append( ( photo[ 'photo-url-1280' ], tags ) )
							except: pass
							
						
					
				
			
		
		return results
		
	
	def GetTags( self, url, tags ): return tags
	
class ImportArgsGenerator( object ):
	
	def __init__( self, job_key, item, advanced_import_options ):
		
		self._job_key = job_key
		self._item = item
		self._advanced_import_options = advanced_import_options
		
	
	def __call__( self ):
		
		try:
			
			( result, media_result ) = self._CheckCurrentStatus()
			
			if result == 'new':
				
				( name, temp_path, service_keys_to_tags, url ) = self._GetArgs()
				
				self._job_key.SetVariable( 'status', 'importing' )
				
				( result, media_result ) = HC.app.WriteSynchronous( 'import_file', temp_path, advanced_import_options = self._advanced_import_options, service_keys_to_tags = service_keys_to_tags, generate_media_result = True, url = url )
				
			
			self._job_key.SetVariable( 'result', result )
			
			if result in ( 'successful', 'redundant' ):
				
				page_key = self._job_key.GetVariable( 'page_key' )
				
				if media_result is not None and page_key is not None:
					
					HC.pubsub.pub( 'add_media_results', page_key, ( media_result, ) )
					
					
				
			
			self._job_key.SetVariable( 'status', '' )
			
			self._job_key.Finish()
			
			self._CleanUp() # e.g. possibly delete the file for hdd importargsgenerator
			
		except Exception as e:
			
			self._job_key.SetVariable( 'result', 'failed' )
			
			if 'name' in locals(): HC.ShowText( 'There was a problem importing ' + name + '!' )
			
			HC.ShowException( e )
			
			time.sleep( 2 )
			
			self._job_key.Cancel()
			
		
	
	def _CleanUp( self ): pass
	
	def _CheckCurrentStatus( self ): return ( 'new', None )
	
class ImportArgsGeneratorGallery( ImportArgsGenerator ):
	
	def __init__( self, job_key, item, advanced_import_options, advanced_tag_options, downloaders_factory ):
		
		ImportArgsGenerator.__init__( self, job_key, item, advanced_import_options )
		
		self._advanced_tag_options = advanced_tag_options
		self._downloaders_factory = downloaders_factory
		
	
	def _GetArgs( self ):
		
		url_args = self._item
		
		url = url_args[0]
		
		self._job_key.SetVariable( 'status', 'downloading' )
		
		downloader = self._downloaders_factory( 'example' )[0]
		
		def hook( range, value ):
			
			self._job_key.SetVariable( 'range', range )
			self._job_key.SetVariable( 'value', value )
			
		
		downloader.AddReportHook( hook )
		
		do_tags = len( self._advanced_tag_options ) > 0
		
		if do_tags: ( temp_path, tags ) = downloader.GetFileAndTags( *url_args )
		else:
			
			temp_path = downloader.GetFile( *url_args )
			
			tags = []
			
		
		downloader.ClearReportHooks()
		
		service_keys_to_tags = ConvertTagsToServiceKeysToTags( tags, self._advanced_tag_options )
		
		time.sleep( 3 )
		
		return ( url, temp_path, service_keys_to_tags, url )
		
	
	def _CheckCurrentStatus( self ):
		
		url_args = self._item
		
		url = url_args[0]
		
		self._job_key.SetVariable( 'status', 'checking url status' )
		
		downloader = self._downloaders_factory( 'example' )[0]
		
		( status, hash ) = HC.app.Read( 'url_status', url )
		
		if status == 'deleted' and 'exclude_deleted_files' not in self._advanced_import_options: status = 'new'
		
		if status == 'redundant':
			
			( media_result, ) = HC.app.ReadDaemon( 'media_results', HC.LOCAL_FILE_SERVICE_KEY, ( hash, ) )
			
			do_tags = len( self._advanced_tag_options ) > 0
			
			if do_tags:
				
				tags = downloader.GetTags( *url_args )
				
				service_keys_to_tags = ConvertTagsToServiceKeysToTags( tags, self._advanced_tag_options )
				
				service_keys_to_content_updates = ConvertServiceKeysToTagsToServiceKeysToContentUpdates( hash, service_keys_to_tags )
				
				HC.app.Write( 'content_updates', service_keys_to_content_updates )
				
				time.sleep( 3 )
				
			
			return ( status, media_result )
			
		else: return ( status, None )
		
	
class ImportArgsGeneratorHDD( ImportArgsGenerator ):
	
	def __init__( self, job_key, item, advanced_import_options, paths_to_tags, delete_after_success ):
		
		ImportArgsGenerator.__init__( self, job_key, item, advanced_import_options )
		
		self._paths_to_tags = paths_to_tags
		self._delete_after_success = delete_after_success
		
	
	def _CleanUp( self ):
		
		result = self._job_key.GetVariable( 'result' )
		
		if self._delete_after_success and result in ( 'successful', 'redundant' ):
			
			( path_type, path_info ) = self._item
			
			if path_type == 'path':
				
				path = path_info
				
				try: os.remove( path )
				except: pass
				
			
		
	
	def _GetArgs( self ):
		
		self._job_key.SetVariable( 'status', 'reading from hdd' )
		
		( path_type, path_info ) = self._item
		
		service_keys_to_tags = {}
		
		if path_type == 'path':
			
			path = path_info
			
			if path in self._paths_to_tags: service_keys_to_tags = self._paths_to_tags[ path ]
			
		elif path_type == 'zip':
			
			( zip_path, name ) = path_info
			
			path = HC.GetTempPath()
			
			with open( path, 'wb' ) as f:
				
				with zipfile.ZipFile( zip_path, 'r' ) as z: f.write( z.read( name ) )
				
			
			pretty_path = zip_path + os.path.sep + name
			
			if pretty_path in self._paths_to_tags: service_keys_to_tags = self._paths_to_tags[ pretty_path ]
			
		
		return ( path, path, service_keys_to_tags, None )
		
	
class ImportArgsGeneratorThread( ImportArgsGenerator ):
	
	def __init__( self, job_key, item, advanced_import_options, advanced_tag_options ):
		
		ImportArgsGenerator.__init__( self, job_key, item, advanced_import_options )
		
		self._advanced_tag_options = advanced_tag_options
		
	
	def _GetArgs( self ):
		
		self._job_key.SetVariable( 'status', 'downloading' )
		
		( md5, image_url, filename ) = self._item
		
		def hook( range, value ):
			
			self._job_key.SetVariable( 'range', range )
			self._job_key.SetVariable( 'value', value )
			
		
		temp_path = HC.http.Request( HC.GET, image_url, report_hooks = [ hook ], response_to_path = True )
		
		tags = [ 'filename:' + filename ]
		
		service_keys_to_tags = ConvertTagsToServiceKeysToTags( tags, self._advanced_tag_options )
		
		time.sleep( 3 )
		
		return ( image_url, temp_path, service_keys_to_tags, image_url )
		
	
	def _CheckCurrentStatus( self ):
		
		self._job_key.SetVariable( 'status', 'checking md5 status' )
		
		( md5, image_url, filename ) = self._item
		
		( status, hash ) = HC.app.Read( 'md5_status', md5 )
		
		if status == 'deleted' and 'exclude_deleted_files' not in self._advanced_import_options: status = 'new'
		
		if status == 'redundant':
			
			( media_result, ) = HC.app.ReadDaemon( 'media_results', HC.LOCAL_FILE_SERVICE_KEY, ( hash, ) )
			
			do_tags = len( self._advanced_tag_options ) > 0
			
			if do_tags:
				
				tags = [ 'filename:' + filename ]
				
				service_keys_to_tags = ConvertTagsToServiceKeysToTags( tags, self._advanced_tag_options )
				
				service_keys_to_content_updates = ConvertServiceKeysToTagsToServiceKeysToContentUpdates( hash, service_keys_to_tags )
				
				HC.app.Write( 'content_updates', service_keys_to_content_updates )
				
				time.sleep( 3 )
				
			
			return ( status, media_result )
			
		else: return ( status, None )
		
	
class ImportArgsGeneratorURLs( ImportArgsGenerator ):
	
	def _GetArgs( self ):
		
		url = self._item
		
		self._job_key.SetVariable( 'status', 'downloading' )
		
		def hook( range, value ):
			
			self._job_key.SetVariable( 'range', range )
			self._job_key.SetVariable( 'value', value )
			
		
		temp_path = HC.http.Request( HC.GET, url, report_hooks = [ hook ], response_to_path = True )
		
		service_keys_to_tags = {}
		
		return ( url, temp_path, service_keys_to_tags, url )
		
	
	def _CheckCurrentStatus( self ):
		
		url = self._item
		
		self._job_key.SetVariable( 'status', 'checking url status' )
		
		( status, hash ) = HC.app.Read( 'url_status', url )
		
		if status == 'deleted' and 'exclude_deleted_files' not in self._advanced_import_options: status = 'new'
		
		if status == 'redundant':
			
			( media_result, ) = HC.app.ReadDaemon( 'media_results', HC.LOCAL_FILE_SERVICE_KEY, ( hash, ) )
			
			return ( status, media_result )
			
		else: return ( status, None )
		
	
class ImportController( object ):
    
    def __init__( self, import_args_generator_factory, import_queue_builder_factory, page_key = None ):
        
        self._controller_job_key = self._GetNewJobKey( 'controller' )
        
        self._import_args_generator_factory = import_args_generator_factory
        self._import_queue_builder_factory = import_queue_builder_factory
        self._page_key = page_key
        
        self._import_job_key = self._GetNewJobKey( 'import' )
        self._import_queue_job_key = self._GetNewJobKey( 'import_queue' )
        self._import_queue_builder_job_key = self._GetNewJobKey( 'import_queue_builder' )
        self._pending_import_queue_jobs = []
        
        self._lock = threading.Lock()
        
    
    def _GetNewJobKey( self, job_type ):
        
        job_key = HC.JobKey( pausable = True, cancellable = True )
        
        if job_type == 'controller':
            
            job_key.SetVariable( 'num_successful', 0 )
            job_key.SetVariable( 'num_failed', 0 )
            job_key.SetVariable( 'num_deleted', 0 )
            job_key.SetVariable( 'num_redundant', 0 )
            
        else:
            
            job_key.SetVariable( 'status', '' )
            
            if job_type == 'import':
                
                job_key.SetVariable( 'page_key', self._page_key )
                job_key.SetVariable( 'range', 1 )
                job_key.SetVariable( 'value', 0 )
                
            elif job_type == 'import_queue':
                
                job_key.SetVariable( 'queue_position', 0 )
                
            elif job_type == 'import_queue_builder':
                
                job_key.SetVariable( 'queue', [] )
                
            
        
        return job_key
        
    
    def CleanBeforeDestroy( self ): self._controller_job_key.Cancel()
    
    def GetJobKey( self, job_type ):
        
        with self._lock:
            
            if job_type == 'controller': return self._controller_job_key
            elif job_type == 'import': return self._import_job_key
            elif job_type == 'import_queue': return self._import_queue_job_key
            elif job_type == 'import_queue_builder': return self._import_queue_builder_job_key
            
        
    
    def GetPendingImportQueueJobs( self ):
        
        with self._lock: return self._pending_import_queue_jobs
        
    
    def PendImportQueueJob( self, job ):
        
        with self._lock: self._pending_import_queue_jobs.append( job )
        
    
    def RemovePendingImportQueueJob( self, job ):
        
        with self._lock:
            
            if job in self._pending_import_queue_jobs: self._pending_import_queue_jobs.remove( job )
            
        
    
    def MovePendingImportQueueJobUp( self, job ):
        
        with self._lock:
            
            if job in self._pending_import_queue_jobs:
                
                index = self._pending_import_queue_jobs.index( job )
                
                if index > 0:
                    
                    self._pending_import_queue_jobs.remove( job )
                    
                    self._pending_import_queue_jobs.insert( index - 1, job )
                    
                
            
        
    
    def MovePendingImportQueueJobDown( self, job ):
        
        with self._lock:
            
            if job in self._pending_import_queue_jobs:
                
                index = self._pending_import_queue_jobs.index( job )
                
                if index + 1 < len( self._pending_import_queue_jobs ):
                    
                    self._pending_import_queue_jobs.remove( job )
                    
                    self._pending_import_queue_jobs.insert( index + 1, job )
                    
                
            
        
    
    def MainLoop( self ):
        
        try:
            
            while not self._controller_job_key.IsDone():
                
                while self._controller_job_key.IsPaused():
                    
                    time.sleep( 0.1 )
                    
                    self._import_job_key.Pause()
                    self._import_queue_job_key.Pause()
                    self._import_queue_builder_job_key.Pause()
                    
                    if HC.shutdown or self._controller_job_key.IsDone(): break
                    
                
                if HC.shutdown or self._controller_job_key.IsDone(): break
                
                with self._lock:
                    
                    queue_position = self._import_queue_job_key.GetVariable( 'queue_position' )
                    queue = self._import_queue_builder_job_key.GetVariable( 'queue' )
            
                    if self._import_job_key.IsDone():
                        
                        result = self._import_job_key.GetVariable( 'result' )
                        
                        variable_name = 'num_' + result
                        
                        num_result = self._controller_job_key.GetVariable( variable_name )
                        
                        self._controller_job_key.SetVariable( variable_name, num_result + 1 )
                        
                        self._import_job_key = self._GetNewJobKey( 'import' )
                        
                        queue_position += 1
                        
                        self._import_queue_job_key.SetVariable( 'queue_position', queue_position )
                        
                    
                    position_string = HC.u( queue_position + 1 ) + '/' + HC.u( len( queue ) )
                    
                    if self._import_queue_job_key.IsPaused(): self._import_queue_job_key.SetVariable( 'status', 'paused at ' + position_string )
                    elif self._import_queue_job_key.IsWorking():
                        
                        if self._import_job_key.IsWorking():
                            
                            self._import_queue_job_key.SetVariable( 'status', 'processing ' + position_string )
                            
                        else:
                            
                            if queue_position < len( queue ):
                                
                                self._import_queue_job_key.SetVariable( 'status', 'preparing ' + position_string )
                                
                                self._import_job_key.Begin()
                                
                                item = queue[ queue_position ]
                                
                                args_generator = self._import_args_generator_factory( self._import_job_key, item )
                                
                                HydrusThreading.CallToThread( args_generator )
                                
                            else:
                                
                                if self._import_queue_builder_job_key.IsWorking(): self._import_queue_job_key.SetVariable( 'status', 'waiting for more items' )
                                else: self._import_queue_job_key.Finish()
                                
                            
                        
                    else:
                        
                        if self._import_queue_job_key.IsDone():
                            
                            if self._import_queue_job_key.IsCancelled(): status = 'cancelled at ' + position_string
                            else: status = 'done'
                            
                            self._import_queue_job_key = self._GetNewJobKey( 'import_queue' )
                            
                            self._import_queue_builder_job_key = self._GetNewJobKey( 'import_queue_builder' )
                            
                        else: status = ''
                        
                        self._import_queue_job_key.SetVariable( 'status', status )
                        
                        if len( self._pending_import_queue_jobs ) > 0:
                            
                            self._import_queue_job_key.Begin()
                            
                            self._import_queue_builder_job_key.Begin()
                            
                            item = self._pending_import_queue_jobs.pop( 0 )
                            
                            queue_builder = self._import_queue_builder_factory( self._import_queue_builder_job_key, item )
                            
                            # make it a daemon, not a thread job, as it has a loop!
                            threading.Thread( target = queue_builder ).start()
                            
                        
                    
                
                time.sleep( 0.05 )
                
            
        except Exception as e:
            
            HC.ShowException( e )
            
        finally:
            
            self._import_job_key.Cancel()
            self._import_queue_job_key.Cancel()
            self._import_queue_builder_job_key.Cancel()
            
        
    
    def StartDaemon( self ): threading.Thread( target = self.MainLoop ).start()
    
class ImportQueueBuilder( object ):
	
	def __init__( self, job_key, item ):
		
		self._job_key = job_key
		self._item = item
		
	
	def __call__( self ):
		
		queue = self._item
		
		self._job_key.SetVariable( 'queue', queue )
		
		self._job_key.Finish()
		
	
class ImportQueueBuilderGallery( ImportQueueBuilder ):
	
	def __init__( self, job_key, item, downloaders_factory ):
		
		ImportQueueBuilder.__init__( self, job_key, item )
		
		self._downloaders_factory = downloaders_factory
		
	
	def __call__( self ):
		
		try:
			
			raw_query = self._item
			
			downloaders = list( self._downloaders_factory( raw_query ) )
			
			downloaders[0].SetupGallerySearch() # for now this is cookie-based for hf, so only have to do it on one
			
			total_urls_found = 0
			
			while True:
				
				downloaders_to_remove = []
				
				for downloader in downloaders:
					
					while self._job_key.IsPaused():
						
						time.sleep( 0.1 )
						
						self._job_key.SetVariable( 'status', 'paused after ' + HC.u( total_urls_found ) + ' urls' )
						
						if HC.shutdown or self._job_key.IsDone(): break
						
					
					if HC.shutdown or self._job_key.IsDone(): break
					
					self._job_key.SetVariable( 'status', 'found ' + HC.u( total_urls_found ) + ' urls' )
					
					time.sleep( 5 )
					
					page_of_url_args = downloader.GetAnotherPage()
					
					total_urls_found += len( page_of_url_args )
					
					if len( page_of_url_args ) == 0: downloaders_to_remove.append( downloader )
					else:
						
						queue = self._job_key.GetVariable( 'queue' )
						
						queue = list( queue )
						
						queue.extend( page_of_url_args )
						
						self._job_key.SetVariable( 'queue', queue )
						
					
				
				for downloader in downloaders_to_remove: downloaders.remove( downloader )
				
				if len( downloaders ) == 0: break
				
				while self._job_key.IsPaused():
					
					time.sleep( 0.1 )
					
					self._job_key.SetVariable( 'status', 'paused after ' + HC.u( total_urls_found ) + ' urls' )
					
					if HC.shutdown or self._job_key.IsDone(): break
					
				
				if HC.shutdown or self._job_key.IsDone(): break
				
			
			self._job_key.SetVariable( 'status', 'finished. found ' + HC.u( total_urls_found ) + ' urls' )
			
			time.sleep( 5 )
			
			self._job_key.SetVariable( 'status', '' )
			
		except Exception as e:
			
			self._job_key.SetVariable( 'status', HC.u( e ) )
			
			HC.ShowException( e )
			
			time.sleep( 2 )
			
		finally: self._job_key.Finish()
		
	
class ImportQueueBuilderURLs( ImportQueueBuilder ):
	
	def __call__( self ):
		
		try:
			
			url = self._item
			
			self._job_key.SetVariable( 'status', 'Connecting to address' )
			
			try: html = HC.http.Request( HC.GET, url )
			except: raise Exception( 'Could not download that url' )
			
			self._job_key.SetVariable( 'status', 'parsing html' )
			
			try: urls = ParsePageForURLs( html, url )
			except: raise Exception( 'Could not parse that URL\'s html' )
			
			queue = urls
			
			self._job_key.SetVariable( 'queue', queue )
			
		except Exception as e:
			
			self._job_key.SetVariable( 'status', HC.u( e ) )
			
			HC.ShowException( e )
			
			time.sleep( 2 )
			
		finally: self._job_key.Finish()
		
	
class ImportQueueBuilderThread( ImportQueueBuilder ):
	
	def __call__( self ):
		
		try:
			
			( json_url, image_base ) = self._item
			
			last_thread_check = 0
			image_infos_already_added = set()
			
			first_run = True
			manual_refresh = False
			
			while True:
				
				if not first_run:
					
					thread_times_to_check = self._job_key.GetVariable( 'thread_times_to_check' )
					
					while thread_times_to_check == 0:
						
						self._job_key.SetVariable( 'status', 'checking is finished' )
						
						time.sleep( 1 )
						
						if self._job_key.IsCancelled(): break
						
						thread_times_to_check = self._job_key.GetVariable( 'thread_times_to_check' )
						
					
				
				while self._job_key.IsPaused():
					
					time.sleep( 0.1 )
					
					self._job_key.SetVariable( 'status', 'paused' )
					
					if HC.shutdown or self._job_key.IsDone(): break
					
				
				if HC.shutdown or self._job_key.IsDone(): break
				
				thread_time = self._job_key.GetVariable( 'thread_time' )
				
				if thread_time < 30: thread_time = 30
				
				next_thread_check = last_thread_check + thread_time
				
				manual_refresh = self._job_key.GetVariable( 'manual_refresh' )
				
				not_too_soon_for_manual_refresh = HC.GetNow() - last_thread_check > 10
				
				if ( manual_refresh and not_too_soon_for_manual_refresh ) or next_thread_check < HC.GetNow():
					
					self._job_key.SetVariable( 'status', 'checking thread' )
					
					try:
						
						raw_json = HC.http.Request( HC.GET, json_url )
						
						json_dict = json.loads( raw_json )
						
						posts_list = json_dict[ 'posts' ]
						
						image_infos = []
						
						for post in posts_list:
							
							if 'md5' not in post: continue
							
							image_md5 = post[ 'md5' ].decode( 'base64' )
							image_url = image_base + HC.u( post[ 'tim' ] ) + post[ 'ext' ]
							image_original_filename = post[ 'filename' ] + post[ 'ext' ]
							
							image_infos.append( ( image_md5, image_url, image_original_filename ) )
							
						
						image_infos_i_can_add = [ image_info for image_info in image_infos if image_info not in image_infos_already_added ]
						
						image_infos_already_added.update( image_infos_i_can_add )
						
						if len( image_infos_i_can_add ) > 0:
							
							queue = self._job_key.GetVariable( 'queue' )
							
							queue = list( queue )
							
							queue.extend( image_infos_i_can_add )
							
							self._job_key.SetVariable( 'queue', queue )
							
						
					except HydrusExceptions.NotFoundException: raise Exception( 'Thread 404' )
					except Exception as e:
						
						self._job_key.SetVariable( 'status', HC.u( e ) )
						
						HC.ShowException( e )
						
						time.sleep( 2 )
						
					
					last_thread_check = HC.GetNow()
					
					if first_run: first_run = False
					elif manual_refresh: self._job_key.SetVariable( 'manual_refresh', False )
					else:
						
						if thread_times_to_check > 0: self._job_key.SetVariable( 'thread_times_to_check', thread_times_to_check - 1 )
						
					
				else: self._job_key.SetVariable( 'status', 'rechecking thread ' + HC.ConvertTimestampToPrettyPending( next_thread_check ) )
				
				time.sleep( 0.1 )
				
			
		except Exception as e:
			
			self._job_key.SetVariable( 'status', HC.u( e ) )
			
			HC.ShowException( e )
			
			time.sleep( 2 )
			
		finally: self._job_key.Finish()
		
	
def THREADDownloadURL( job_key, url, url_string ):
    
    def hook( range, value ):
        
        if range is None: text = url_string + ' - ' + HC.ConvertIntToBytes( value )
        else: text = url_string + ' - ' + HC.ConvertIntToBytes( value ) + '/' + HC.ConvertIntToBytes( range )
        
        job_key.SetVariable( 'popup_message_text_1', text )
        job_key.SetVariable( 'popup_message_gauge_1', ( value, range ) )
        
    
    temp_path = HC.http.Request( HC.GET, url, response_to_path = True, report_hooks = [ hook ] )
    
    job_key.DeleteVariable( 'popup_message_gauge_1' )
    job_key.SetVariable( 'popup_message_text_1', 'importing ' + url_string )
    
    ( result, hash ) = HC.app.WriteSynchronous( 'import_file', temp_path )
    
    if result in ( 'successful', 'redundant' ):
        
        job_key.SetVariable( 'popup_message_text_1', url_string )
        job_key.SetVariable( 'popup_message_files', { hash } )
        
    elif result == 'deleted':
        
        job_key.SetVariable( 'popup_message_text_1', url_string + ' was already deleted!' )
        
    
def Parse4chanPostScreen( html ):
	
	soup = bs4.BeautifulSoup( html )
	
	title_tag = soup.find( 'title' )
	
	if title_tag.string == 'Post successful!': return ( 'success', None )
	elif title_tag.string == '4chan - Banned':
		
		print( repr( soup ) )
		
		text = 'You are banned from this board! html written to log.'
		
		HC.ShowText( text )
		
		return ( 'big error', text )
		
	else:
		
		try:
			
			problem_tag = soup.find( id = 'errmsg' )
			
			if problem_tag is None:
				
				try: print( repr( soup ) )
				except: pass
				
				text = 'Unknown problem; html written to log.'
				
				HC.ShowText( text )
				
				return ( 'error', text )
				
			
			problem = HC.u( problem_tag )
			
			if 'CAPTCHA' in problem: return ( 'captcha', None )
			elif 'seconds' in problem: return ( 'too quick', None )
			elif 'Duplicate' in problem: return ( 'error', 'duplicate file detected' )
			else: return ( 'error', problem )
			
		except: return ( 'error', 'unknown error' )
		
	
def ParsePageForURLs( html, starting_url ):
	
	soup = bs4.BeautifulSoup( html )
	
	all_links = soup.find_all( 'a' )
	
	links_with_images = [ link for link in all_links if len( link.find_all( 'img' ) ) > 0 ]
	
	urls = [ urlparse.urljoin( starting_url, link[ 'href' ] ) for link in links_with_images ]
	
	# old version included (images that don't have a link wrapped around them)'s src
	
	return urls
	