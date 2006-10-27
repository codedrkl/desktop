"""
This file is part of SDict Viewer (http://sdictviewer.sf.net) - dictionary that uses 
data bases in AXMASoft's open dictionary format.
Copyright (C) 2006 Igor Tkach
"""

import zlib
import bz2
import struct

"""
+--------+------------+-----------+--------------------------------------------+
| Offset | Len, bytes | Content   |              Description                   |
+--------+------------+-----------+--------------------------------------------+
| 0x0    | 4          | uint8_t[] | Signature, 'sdct'                          |
| 0x4    | 3          | uint8_t[] | Input language                             |
| 0x7    | 3          | uint8_t[] | Output language                            |
| 0xa    | 1          | uint8_t   | Compression method            : (bytes 0-3)|
|        |            |           |             and index levels  : (bytes 4-7)|
| 0xb    | 4          | uint32_t  | Amount of words                            |
| 0xf    | 4          | uint32_t  | Length of short index                      |
| 0x13   | 4          | uint32_t  | Offset of 'title' unit                     |
| 0x17   | 4          | uint32_t  | Offset of 'copyright' unit                 |
| 0x1b   | 4          | uint32_t  | Offset of 'version' unit                   |
| 0x1f   | 4          | uint32_t  | Offset of short index                      |
| 0x23   | 4          | uint32_t  | Offset of full index                       |
| 0x27   | 4          | uint32_t  | Offset of articles                         |
+--------+------------+-----------+--------------------------------------------+
"""
    
class GzipCompression:
    
    def __str__(self):
        return "gzip"
    
    def decompress(self, string):
        return zlib.decompress(string)
    
class Bzip2Compression:    
    
    def __str__(self):
        return "bzip2"
    
    def decompress(self, string):
        return bz2.decompress(string)
    
class NoCompression:
    
    def __str__(self):
        return "no compression"
        
    def decompress(self, string):
        return string
    
def read_raw(s, fe):
    return s[fe.offset:fe.offset + fe.length]

def read_str(s, fe):
    raw = read_raw(s, fe)
    return raw.replace('\x00', '');

def read_int(s, fe = None):      
    if fe:
        raw = read_raw(s, fe)
    else:
        raw = s
    return struct.unpack('<I', raw)[0]    

def read_short(raw):  
    return struct.unpack('<H', raw)[0]    

def read_byte(raw):  
    return struct.unpack('<B', raw)[0]    

class FormatElement:
    def __init__(self, offset, length, elementType = None):
        self.offset = offset
        self.length = length
        self.elementType = elementType

class FullIndexItem:
    def __init__(self, next_ptr, prev_ptr, word, article_ptr):
        self.next_ptr = next_ptr
        self.prev_ptr = prev_ptr
        self.word = word
        self.article_ptr = article_ptr
    
class Header:
                    
    f_signature = FormatElement(0x0, 4)
    f_input_lang = FormatElement(0x4, 3)
    f_output_lang = FormatElement(0x7, 3)
    f_compression = FormatElement(0xa, 1)
    f_num_of_words = FormatElement(0xb, 4)
    f_length_of_short_index=FormatElement(0xf, 4)
    f_title=FormatElement(0x13, 4)
    f_copyright=FormatElement(0x17, 4)
    f_version=FormatElement(0x1b, 4)
    f_short_index=FormatElement(0x1f, 4)
    f_full_index=FormatElement(0x23, 4)
    f_articles=FormatElement(0x27, 4)
                        
    def parse(self, str):
        self.signature = read_str(str, self.f_signature)
        if self.signature != 'sdct':
            raise DictFormatError, "Not a valid sdict dictionary"
        self.word_lang = read_str(str, self.f_input_lang)
        self.article_lang = read_str(str, self.f_output_lang)
        self.short_index_length = read_int(str, self.f_length_of_short_index)
        comp_and_index_levels_byte = read_byte(read_raw(str, self.f_compression)) 
        self.compressionType = comp_and_index_levels_byte & int("00001111", 2)
        self.short_index_depth = comp_and_index_levels_byte >> 4        
        self.num_of_words = read_int(str, self.f_num_of_words)
        self.title_offset = read_int(str, self.f_title)
        self.copyright_offset = read_int(str, self.f_copyright)
        self.version_offset = read_int(str, self.f_version)
        self.articles_offset = read_int(str, self.f_articles)
        self.short_index_offset = read_int(str, self.f_short_index)
        self.full_index_offset = read_int(str, self.f_full_index)
        
    
compressions = {0:NoCompression(), 1:GzipCompression(), 2:Bzip2Compression()}
        
class DictFormatError(Exception):
     def __init__(self, value):
         self.value = value
     def __str__(self):
         return repr(self.value)        
        
class SDictionary:         
    
    def __init__(self, file_name, encoding = "utf-8"):    
        self.encoding = encoding
        self.file_name = file_name
        self.file = open(file_name, "rb");
        self.header = Header()
        self.header.parse(self.file.read(43))  
        self.compression = compressions[self.header.compressionType]    
        self.title = self.read_unit(self.header.title_offset)  
        self.version = self.read_unit(self.header.version_offset)  
        self.copyright = self.read_unit(self.header.copyright_offset)
        self.current_pos = self.header.full_index_offset
        self.read_short_index()
        
    def read_unit(self, pos):
        f = self.file
        f.seek(pos);
        record_length= read_int(f.read(4))
        s = f.read(record_length)
        s = self.compression.decompress(s)
        return s
    
    def read_short_index(self):        
        self.file.seek(self.header.short_index_offset)
        s_index_depth = self.header.short_index_depth
        short_index_str = self.file.read((s_index_depth*4 + 4)*self.header.short_index_length)
        short_index_str = self.compression.decompress(short_index_str)                
        index_length = self.header.short_index_length
        short_index = [{} for i in xrange(s_index_depth+1)]
        depth_range = xrange(s_index_depth)
        for i in xrange(index_length):
            entry_start = i* (s_index_depth+1)*4
            short_word = u''
            for j in depth_range:
                start_index = entry_start+j*4
                end_index = start_index+4
                uchar_code =  read_int(short_index_str[start_index:end_index])
                if uchar_code != 0:
                    short_word += unichr(uchar_code)            
            pointer_start = entry_start+s_index_depth*4
            pointer = read_int(short_index_str[pointer_start:pointer_start+4])            
            short_word_len = len(short_word)            
            short_index[short_word_len][short_word.encode(self.encoding)] = pointer
        self.short_index = short_index
            
    def get_search_pos_for(self, word):
        search_pos = -1
        starts_with = ""
        s_index_depth = self.header.short_index_depth
        for i in xrange(1, s_index_depth + 1):
            index = self.short_index[i]    
            try:
                u_word = word.decode(self.encoding)
                u_subword = u_word[:i]
                subword = u_subword.encode(self.encoding)
                if index.has_key(subword):
                    search_pos = index[subword]
                    starts_with = subword
            except UnicodeDecodeError, ex:
                print ex            
        return search_pos, starts_with
               
    def lookup(self, word):
        search_pos, starts_with = self.get_search_pos_for(word)
        if search_pos > -1:
            next_word = None
            next_ptr = search_pos
            current_pos = self.header.full_index_offset
            index_item = None
            i = -1
            while next_word != word:
                i += 1
                current_pos += next_ptr
                index_item = self.read_full_index_item(current_pos)
                next_word = index_item.word
                next_ptr = index_item.next_ptr
                if not next_word.startswith(starts_with):
                    break
                if next_ptr == 0:
                    break
            if index_item != None and index_item.word == word:
                return self.read_article(index_item.article_ptr)
        return None
                            
    def get_word_list(self, start_word, n):
        search_pos, starts_with = self.get_search_pos_for(start_word)
        word_list = []
        if search_pos > -1:
            next_word = None
            next_ptr = search_pos
            current_pos = self.header.full_index_offset
            index_item = None
            while True:
                current_pos += next_ptr
                index_item = self.read_full_index_item(current_pos)
                next_word = index_item.word
                next_ptr = index_item.next_ptr
                if not next_word.startswith(starts_with):
                    break                
                if next_ptr == 0:
                    break
                if next_word.startswith(start_word):
                    word_list.append(next_word)
                if len(word_list) == n:
                    break
        return word_list
        
            
    def read_full_index_item(self, pointer):
        if (pointer >= self.header.articles_offset):
            print 'Warning: attempt to read word from illegal position in dict file'        
            return None
        f = self.file
        if (f.tell() != pointer):
            f.seek(pointer)
        next_word = read_short(f.read(2))
        prev_word = read_short(f.read(2))
        article_pointer = read_int(f.read(4))
        if next_word != 0:
            word_length = next_word - 8        
            word = f.read(word_length)
        else:
            word = None    
        return FullIndexItem(next_word, prev_word, word, article_pointer)
        
    def read_article(self, pointer):
        return self.read_unit(self.header.articles_offset + pointer)        
    
    def close(self):
        self.file.close()        