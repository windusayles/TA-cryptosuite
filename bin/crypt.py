#!/usr/bin/env python

""" 
    Implementation of the custom Splunk> search command "crypt" used
    for encrypting fields using RSA or decrypting RSA encrypted fields 
    during search time.
"""

from __future__ import absolute_import
import sys, base64, re, binascii

import rsa
from rsa._compat import b

from xml.dom import minidom
from xml.dom.minidom import Node

import M2Crypto
import splunklib.client as client
from splunklib.searchcommands import \
     dispatch, StreamingCommand, Configuration, Option, validators

@Configuration()
class CryptCommand(StreamingCommand):
    """ 
    ##Syntax

    crypt mode=<d|e> key=<file_path> [keyencryption=<boolean> | randpadding=<boolean>] <field-list>

    ##Description
    
    Values of fields provided by `field-list` are encrypted or decrypted with
    the key provided by `key` depending on the mode set by `mode`.
    
    When setting `mode=e` encryption is specified.
    Fields provided by `field-list` are encrypted using the PEM key file provided by `key`.

    When setting `mode=d` decryption is specified.
    Fields provided by `field-list` are decrypted using the PEM key file provided by `key`.   
    When using an encrypted private key for field decryption, set the optional parameter 
    `keyencryption` to true. The password to use will be drawn from Splunk's password storage.
    Passwords can be set per user and key file in the app's set up screen.
    Currently supported algorithms for key encryption are AES256-CBC, DES-CBC and DES-EDE3-CBC.

    ##Requirements

    A valid RSA key-pair stored in separat .pem files, as generated by openssl.
          
    ##Examples

    Decrypt the content of the already RSA encrypted field `username` for output in plain text
    using the key file `lib/keys/private.pem`.
    The key file is encrypted with AES256-CBC, so set keyencryption to true.
    The correspondig password has to be set via the app's set up screen prior to using the key.
    
    search sourcetype="server::access" | crypt mode=d key=lib/keys/private.pem
    keyencryption=true username | table _time action username
    
    Encrypt the values of the fields `subject` and `content` of sourcetype `mail` 
    stored in plain text.
    
    search sourcetype="mail" | crypt mode=e key=lib/keys/public.pem subject content
    
    Encrypt the values of the field `subject` and `content` of sourcetype `mail` 
    stored in plain text and collect the events in a summary index.
    Note: Since the command does not modify the original fields, you can not collect the 
          events with modified content directly. You have to pre-format the information to
          collect using `table` etc.
    
    search sourcetype="mail" | crypt mode=e key=lib/keys/public.pem subject content | 
    table sender referer subject content | collect index=summary
          
    """
    
    mode = Option(
        doc='''
        **Syntax:** **mode=***<d|e>*
        **Description:** d for decryption or e for encryption''',
        require=True)
    
    key = Option(
        doc='''
        **Syntax:** **key=***<path_to_file>*
        **Description:** .pem file which holds the key to use''',
        require=True, validate=validators.File())

    keyencryption = Option(
        doc='''
        **Syntax:** **keyencryption=***<true|false>*
        **Description:** Specify whether private key is encrypted or not''',
        require=False, validate=validators.Boolean())          

    randpadding = Option(
        doc='''
        **Syntax:** **randpadding=***<true|false>*
        **Description:** Use random padding while encrypting or not''',
        require=False, validate=validators.Boolean())   
        
    def stream(self, records):     
      # Bind to current Splunk session
      #
      service = client.Service(token=self.input_header["sessionKey"])
      f = open('debug', 'r+') 
      # Get user objects
      #
      xml_doc = minidom.parseString(self.input_header["authString"])      
      current_user = xml_doc.getElementsByTagName('userId')[0].firstChild.nodeValue
      kwargs = {"sort_key":"realname", "search":str(current_user), "sort_dir":"asc"}
      users = service.users.list(count=-1,**kwargs)
      user_authorization = 0 
            
      # Check if a valid PEM file was provided
      #
      file_content = self.key.read()
      file_type = 'PEM'
      
      if re.match(r'-----BEGIN .* PUBLIC KEY-----', file_content) is None:
          if re.match(r'-----BEGIN .* PRIVATE KEY-----', file_content) is None:
              raise RuntimeWarning('Currently only keys in PEM format are supported. Please specify a valid key file.')  
              # In a future version set file_type = 'DER' at this point

      
      # Handle encryption
      #
      if re.match(r'e', self.mode) is not None:
          # Check if invoking user is authorized to encrypt data
          #
          for user in users:
              if user.name == current_user:
                  for role in user.role_entities:
                      if re.match(r'can_encrypt', role.name) is not None:
                          user_authorization = 1
                      for imported_role in role.imported_roles:
                          if re.match(r'can_encrypt', imported_role) is not None:
                              user_authorization = 1
                              
          if user_authorization == 1:                  
              # Decode key file's content
              #
              try:
                  enc = rsa.key.PublicKey.load_pkcs1(file_content, file_type)
              except:
                  raise RuntimeWarning('Invalid key file has been provided for encryption: %s. Check the provided values of \'key\' and \'keyencryption\'.' % self.key.name)

              # Perform field encryption
              #
              for record in records:
                  for fieldname in self.fieldnames:
                      if fieldname.startswith('_'):
                          continue             
                      try:
                          # Do not use random padding for encryption
                          #
                          if not self.randpadding:
                          #if re.match(r'(false|f|0|n|no)', str(self.randpadding)) is not None:                          
                              record[fieldname] = base64.encodestring(rsa.encrypt_zero_padding(record[fieldname], enc))
                          # Use random padding for encryption
                          #
                          else:                         
                              record[fieldname] = base64.encodestring(rsa.encrypt_rand_padding(record[fieldname], enc))
                      except:
                          print 'Encryption failed: %s' % record[fieldname]
                  yield record
                  
          else:
              raise RuntimeWarning('User \'%s\' is not authorized to perform encryption operations.' % str(current_user))
           
                          
      # Handle decryption
      #
      elif re.match(r'd', self.mode) is not None:
          # Check if invoking user is authorized to decrypt data
          #
          for user in users:
              if user.name == current_user:
                  for role in user.role_entities:
                      if re.match(r'can_decrypt', role.name) is not None:
                          user_authorization = 1
                      for imported_role in role.imported_roles:
                          if re.match(r'can_decrypt', imported_role) is not None:
                              user_authorization = 1
                   
          if user_authorization == 1:
              # Handle key file decryption
              #
              if self.keyencryption:       
                  # Get associated password from Splunk's password storage
                  # Prepare key file decryption
                  #
                  kwargs = {"sort_key":"realm", "search":str(current_user), "sort_dir":"asc"}
                  storage_passwords = service.storage_passwords.list(count=-1,**kwargs)
                  got_password = 0
                  for storage_password in storage_passwords:
                      if storage_password.realm == self.key.name:
                          got_password = 1
                          password = storage_password.clear_password
                          # Decode encrypted key file's content
                          #
                          read_password = lambda *args: str(password)
                          dec = M2Crypto.RSA.load_key(self.key.name, read_password)
                  if got_password == 0:
                      raise ValueError('No password associated with the provided key file for this user has been found. Set a valid password in the app\'s set up screen.')
          
              else:
                  # Decode unencrypted key file's content
                  #
                  try:
                      dec = M2Crypto.RSA.load_key(self.key.name)
                  except:
                      raise RuntimeWarning('Invalid key file has been provided for decryption: %s. Check the provided values of \'key\' and \'keyencryption\'.' % self.key.name)

              # Perform field decryption
              #              
              for record in records:
                  for fieldname in self.fieldnames:
                      if fieldname.startswith('_'):
                          continue   
                      try:
                          record[fieldname] = dec.private_decrypt(base64.decodestring(record[fieldname]), M2Crypto.RSA.pkcs1_padding)
                      except:
                          print 'Decryption failed: %s' % record[fieldname]
                  yield record
                  
          else:
              raise RuntimeWarning('User \'%s\' is not authorized to perform decryption operations.' % str(current_user))
                       
      else:
          raise ValueError('Invalid mode has been set: %s' % mode)
      f.close()
dispatch(CryptCommand, sys.argv, sys.stdin, sys.stdout, __name__)